# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""v10 motion-QUALITY gates (2026-07-31, the "spastic hand" deliverable):
per-region flow vectors, reversal/coherence statistics, qc_motion_quality and
qc_motion_balance."""

import os
from .gates_v7 import _gate_thr, _record_qc


# ── v10 motion-QUALITY gates (2026-07-31, the "spastic hand" deliverable) ────────────
# THE EXISTING MOTION GATES MEASURE THE WRONG QUANTITY AND ACTIVELY REWARD THE DEFECT.
# qc_clip's mean_delta floor and qc_region_flow's min_flow floor ask one question only:
# "did this region move ENOUGH?" A hand that vibrates travels more per sample than a hand
# that writes, so jitter scores BETTER. Measured with the SHIPPING gate itself
# (qc_region_flow, sample_every=4) on the hand box (0.58,0.60,0.83,0.90) of the two
# deliverables the operator judged by eye — v6 "natural, liked" vs v10 "spastic, fast":
#     v6   flow_mean 1.789   churn_p95 0.643  -> region ok = False   (FAILS the liked clip)
#     v10  flow_mean 1.131   churn_p95 0.433  -> region ok = True    (PASSES the bad clip)
# The verdict is exactly INVERTED. Magnitude is not the axis. DIRECTION is.
#
# Per sampled step these gates take the MEAN FLOW VECTOR over the region — a vector, not
# a magnitude. Averaging the field first cancels incoherent per-pixel noise and keeps bulk
# limb travel, which is precisely the difference between a hand going somewhere and a hand
# buzzing in place. From that vector series:
#   reversals_per_s : fraction of consecutive vector pairs whose direction turns more than
#                     90 deg, scaled to per second. Jitter IS direction thrash.
#   net_path        : |sum v| / sum |v|. 1.0 = a straight glide, 0.0 = pure vibration.
#
# MEASURED CALIBRATION (both clips 1664x960, 24fps, 479f; step=2 -> 12 samples/s, 239 steps;
# these reproduce the operator-supplied numbers to 3 decimals, so the metric is the one that
# was calibrated):
#   a_hand (0.58,0.60,0.83,0.90)      v6 "natural"   v10 "spastic"   separation
#     mean |v|      (flow_mean)          0.764           0.666       none, and INVERTED
#     median |v|    (flow_median)        0.232           0.306       none, and INVERTED
#     reversals/s                        3.49            5.82        1.67x   <- discriminator
#     net_path                           0.229           0.167       1.37x   <- discriminator
#
# THRESHOLDS AND WHY:
#   _MOTION_REVERSALS_MAX = 4.5/s  — the geometric mid-gap of 3.49 and 5.82 is 4.51. Keeps
#     29% headroom under the liked clip and fails the bad one by 29%. This is the WIDER of
#     the two separations and the one to trust first.
#   _MOTION_NET_PATH_MIN  = 0.20   — geometric mid-gap of 0.167 and 0.229 is 0.196. HONEST
#     WARNING: this is a THIN gate, ~14% margin either side. It is a corroborator, not a
#     primary. Do not tighten it towards 0.229 chasing sensitivity; v6 is a PASS example and
#     0.21+ would false-fail it.
#   step=2 IS PART OF THE CALIBRATION. Reversal rate aliases DOWN as the sampling interval
#     grows — measured on a_hand: step 1/2/3/4 -> v6 3.71/3.49/2.99/2.19, v10 6.34/5.82/4.51/
#     3.20. At step=4 BOTH clips sit under 4.5/s and the gate goes blind. Any step != 2
#     without explicit bounds is logged as a loud warning rather than silently rescaled.
#   min_flow / max_flow default to None = NOT GATED, deliberately. There is no defensible
#     magnitude default: magnitude ranks these two clips backwards (above). The freeze floor
#     already lives in qc_region_flow; supply these only as a coarse sanity bound.
#
# _MOTION_COHERENCE_FLOOR = 0.05 px/step: direction is UNDEFINED for a region that is not
# moving, and both statistics degenerate into noise readings there. Measured on v6 — the
# clip the operator LIKED — the static regions read c_hands |v| 0.018 net_path 0.146 and
# pipe |v| 0.021 net_path 0.154: both would FALSE-FAIL min_net_path=0.20 while looking
# perfect on screen. So below the floor the coherence checks are REPORTED but not gated
# ('moving': False). A region that is frozen is qc_region_flow's business, not this gate's.
#
# net_path_win (informational, NOT gated by default): the same ratio computed over 1s
# windows and averaged. It separates the hand region BETTER than the whole-clip figure
# (v6 0.562 vs v10 0.292 = 1.93x, against 1.37x) and — the real point — it does not punish
# static regions (v6 c_hands 0.617, pipe 0.559 instead of 0.146/0.154), because a whole-clip
# net_path also counts "the hand went out and came back over 20s" as incoherence. It is
# reported on every region and gateable via min_net_path_win once someone has calibrated it
# on more than two clips. Two clips is not a calibration set; it is an anecdote that happens
# to be right.
#
# qc_motion_balance covers the other half of the operator's complaint: a jittering limb on a
# DEAD FACE. Measured flow_mean ratio a_hand / face-region:
#     face box                            v6      v10
#     a_head  (0.60,0.02,0.96,0.56) prod  4.13    20.50
#     tight   (0.70,0.13,0.88,0.45)       1.61    13.42
#     medium  (0.66,0.10,0.92,0.50)       2.50    17.44
# _MOTION_BALANCE_RATIO_MAX = 7.5 sits in the gap between the WORST v6 (4.13) and the BEST
# v10 (13.42) — geometric mid-gap 7.44 — so the required v6-PASS/v10-FAIL pattern holds for
# every face-box convention measured, not just one. NOTE FOR THE CALLER: the suggested 3.0
# was REJECTED on measurement. With the production a_head box v6 scores 4.13 and 3.0 would
# false-fail the clip the operator likes; 3.0 only works if the face box is cropped tight to
# the face. 7.5 works either way. The ratio is sensitive to how much dead background the
# denominator box contains — crop the face box tight and pass a per-pair override rather
# than trusting one global number.
_MOTION_REVERSALS_MAX = 4.5  # per second, CALIBRATED AT step=2 (see above)
_MOTION_NET_PATH_MIN = 0.20  # |sum v| / sum |v|; thin gate, corroborator only
_MOTION_COHERENCE_FLOOR = 0.05  # px/step |mean vector| below which direction is noise
_MOTION_BALANCE_RATIO_MAX = 7.5  # flow_mean(a) / flow_mean(b)
_MOTION_STEP_CALIBRATED = 2  # the step the thresholds above were measured at
_MOTION_WIN_S = 1.0  # window for the informational net_path_win


def _region_flow_vectors(clip_path, regions, step=2, max_frames=None):
    """Stream a clip ONCE and return the per-region mean-flow-VECTOR series.

    Memory-light on purpose: only the previous crop of each region is retained, never the
    decoded clip (these deliverables are 479 frames of 1664x960 — holding them grayscale
    is 765MB, and this gate wants step=2, i.e. twice the sample density qc_region_flow uses).

    Farneback parameters are IDENTICAL to qc_region_flow's, so the two gates read the same
    flow field and their numbers stay comparable in one report.

    Returns (fps, {name: [(vx, vy), ...]}, {name: [per-pixel mean |flow|, ...]}). The second
    dict is the OLD magnitude metric, carried for side-by-side evidence in the report."""
    import cv2
    import numpy as np

    cap = cv2.VideoCapture(clip_path)
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    if fps <= 1e-3:
        fps = 24.0  # finished-deliverable rate; only scales the /s readout
    step = max(1, int(step or 1))
    prev, vecs, perpix = {}, {n: [] for n in regions}, {n: [] for n in regions}
    i = kept = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if i % step == 0:
            g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            H, W = g.shape[:2]
            for name, box in (regions or {}).items():
                fx0, fy0, fx1, fy1 = box
                y0, y1 = max(0, int(H * fy0)), min(H, int(H * fy1))
                x0, x1 = max(0, int(W * fx0)), min(W, int(W * fx1))
                crop = g[y0:y1, x0:x1] if (y1 - y0) >= 2 and (x1 - x0) >= 2 else None
                p = prev.get(name)
                if crop is not None and p is not None and p.shape == crop.shape:
                    fl = cv2.calcOpticalFlowFarneback(p, crop, None, 0.5, 3, 15, 3, 5, 1.2, 0)
                    vecs[name].append((float(fl[..., 0].mean()), float(fl[..., 1].mean())))
                    perpix[name].append(float(np.sqrt(fl[..., 0] ** 2 + fl[..., 1] ** 2).mean()))
                prev[name] = crop
            kept += 1
            if max_frames and kept >= int(max_frames):
                break
        i += 1
    cap.release()
    return fps, vecs, perpix


def _motion_vector_stats(vec_list, fps, step, win_s=_MOTION_WIN_S):
    """Vector series -> {'flow_mean','flow_median','reversals_per_s','net_path', ...}.

    reversals: angular change between CONSECUTIVE mean vectors, counted when it exceeds
    90 deg, expressed per second (samples/s = fps / step). No magnitude floor is applied to
    the angle test — a floor was measured and rejected: at 0.1 px it drops a low-motion
    region to 0-4 usable pairs, so the rate stops being a rate. Regions that are too still
    for direction to mean anything are excluded by the CALLER's coherence floor instead.

    net_path: |sum v| / sum |v| over the whole series (the gated figure), plus net_path_win,
    the same ratio averaged over ~win_s windows (informational; see the block header)."""
    import math
    import numpy as np

    a = np.asarray(vec_list or [], dtype='float64').reshape(-1, 2)
    if len(a) < 2:
        return None
    mag = np.sqrt((a * a).sum(1))
    rate = float(fps) / max(1, int(step or 1))
    turns, rev = [], 0
    for i in range(len(a) - 1):
        den = float(mag[i] * mag[i + 1])
        if den <= 1e-12:
            continue  # a literally zero step has no direction
        c = float(a[i, 0] * a[i + 1, 0] + a[i, 1] * a[i + 1, 1]) / den
        ang = math.degrees(math.acos(max(-1.0, min(1.0, c))))
        turns.append(ang)
        if ang > 90.0:
            rev += 1
    n_ang = len(turns)
    path = float(mag.sum())
    net = float(math.hypot(float(a[:, 0].sum()), float(a[:, 1].sum()))) / max(path, 1e-9)
    w = max(2, int(round(rate * float(win_s or 1.0))))
    wins = []
    for i in range(0, max(0, len(a) - w + 1), max(1, w // 2)):
        s = a[i : i + w]
        m = float(np.sqrt((s * s).sum(1)).sum())
        if m > 1e-9:
            wins.append(float(math.hypot(float(s[:, 0].sum()), float(s[:, 1].sum()))) / m)
    return {
        'flow_mean': float(mag.mean()),
        'flow_median': float(np.median(mag)),
        'reversals_per_s': (rev / n_ang) * rate if n_ang else 0.0,
        'reversal_frac': (rev / n_ang) if n_ang else 0.0,
        'mean_turn_deg': float(np.mean(turns)) if turns else 0.0,
        'net_path': net,
        'net_path_win': float(np.mean(wins)) if wins else None,
        'n_steps': int(len(a)),
        'n_turns': int(n_ang),
        'samples_per_s': rate,
    }


def qc_motion_quality(
    clip_path,
    regions,
    max_reversals_per_s=None,
    min_net_path=None,
    min_flow=None,
    max_flow=None,
    step=2,
    log_fn=None,
    min_net_path_win=None,
    coherence_floor=None,
    fail_open=True,
):
    """Jitter gate — motion QUALITY, not motion quantity (2026-07-31, the v10 "spastic hand").

    The gates that shipped before this one measure how MUCH a region moves, which ranks a
    vibrating hand above a writing one; on the two reference deliverables the shipping
    qc_region_flow fails the liked clip and passes the bad one (numbers in the block header
    above). This gate measures WHERE the motion goes.

    regions: {name: (fx0, fy0, fx1, fy1)} fractional boxes. Per region, per sampled step
    (every `step`-th frame), the region-MEAN Farneback flow VECTOR is taken, and from that
    series:
      flow_mean / flow_median : mean and median |mean vector| in px/step (reported, and
              gated only if you supply min_flow / max_flow — no default, magnitude does not
              separate natural from spastic and a default would launder the wrong axis)
      reversals_per_s : consecutive vectors turning >90 deg, as a per-second rate
      net_path        : |sum v| / sum |v| — 1.0 straight glide, 0.0 pure vibration
      net_path_win    : net_path over ~1s windows, averaged (informational unless you pass
              min_net_path_win; separates better but is not calibrated beyond two clips)

    Bounds: None -> the calibrated default for reversals (4.5/s) and net_path (0.20);
    scalar -> same for every region; {name: value} -> per region. EVERY SUPPLIED BOUND IS
    GATED — a region passes only if it clears all of them.

    coherence_floor (default 0.05 px/step): a region quieter than this is marked
    'moving': False and its reversals/net_path are REPORTED BUT NOT GATED — direction is
    undefined for something that is not moving, and v6's own static regions score net_path
    0.146-0.154 there, i.e. a floorless gate would fail the reference-good clip.

    step=2 is part of the calibration (reversal rate aliases down at coarser steps); a
    different step with default bounds is logged as a warning and flagged in the output.

    Returns {'ok', 'regions': {name: {'flow_mean','flow_median','reversals_per_s',
    'net_path','ok','reasons', ...}}, 'checks': [...]} and is appended to the active
    DebugRun's qc (report-compatible). Advisory: fail-open on internal error."""
    log = log_fn or (lambda _m: None)
    out = {
        'tag': f'motion_quality:{os.path.basename(clip_path)}',
        'kind': 'motion_quality',
        'path': clip_path,
        'ok': True,
        'regions': {},
        'checks': [],
        'reasons': [],
        'step': int(step or 1),
    }
    try:
        floor = float(coherence_floor) if coherence_floor is not None else _MOTION_COHERENCE_FLOOR
        if int(step or 1) != _MOTION_STEP_CALIBRATED and (max_reversals_per_s is None or min_net_path is None):
            w = (
                f'step={step} but the default bounds were calibrated at '
                f'step={_MOTION_STEP_CALIBRATED}; BOTH defaults drift with the sampling '
                f"interval — measured step 2->4, the bad clip's reversal rate aliases "
                f"DOWN 5.82/s -> 3.20/s (gate goes blind) while the LIKED clip's net_path "
                f'sags 0.229 -> 0.188 (false FAIL). Supply explicit bounds for this step '
                f'or expect both errors'
            )
            out['reasons'].append(w)
            out['step_warning'] = True
            log(f'[qc_motion_quality] WARNING: {w}')
        fps, vecs, perpix = _region_flow_vectors(clip_path, regions or {}, step=step)
        if not regions:
            out['error'] = 'no regions supplied — nothing to measure'
            _record_qc(out)
            return out
        out['fps'] = round(float(fps), 3)
        for name in regions or {}:
            st = _motion_vector_stats(vecs.get(name), fps, step)
            if st is None:
                out['regions'][name] = {'ok': True, 'reasons': ['too few samples to measure'], 'unmeasured': True}
                out['checks'].append(
                    {'check': f'motion_quality:{name}', 'ok': True, 'note': 'too few samples to measure'}
                )
                continue
            pp = perpix.get(name) or []
            r = {
                'flow_mean': round(st['flow_mean'], 4),
                'flow_median': round(st['flow_median'], 4),
                'reversals_per_s': round(st['reversals_per_s'], 3),
                'net_path': round(st['net_path'], 4),
                'net_path_win': (None if st['net_path_win'] is None else round(st['net_path_win'], 4)),
                'mean_turn_deg': round(st['mean_turn_deg'], 2),
                'flow_perpix': round(float(sum(pp) / len(pp)), 4) if pp else None,
                'n_steps': st['n_steps'],
                'samples_per_s': round(st['samples_per_s'], 3),
                'moving': bool(st['flow_mean'] >= floor),
                'reasons': [],
            }
            rev_max = _gate_thr(max_reversals_per_s, name, _MOTION_REVERSALS_MAX)
            net_min = _gate_thr(min_net_path, name, _MOTION_NET_PATH_MIN)
            win_min = _gate_thr(min_net_path_win, name, None)
            fl_min = _gate_thr(min_flow, name, None)
            fl_max = _gate_thr(max_flow, name, None)
            r['bounds'] = {
                'max_reversals_per_s': rev_max,
                'min_net_path': net_min,
                'min_net_path_win': win_min,
                'min_flow': fl_min,
                'max_flow': fl_max,
                'coherence_floor': floor,
            }
            ok = True
            if fl_min is not None and st['flow_mean'] < float(fl_min):
                ok = False
                r['reasons'].append(f'flow_mean {st["flow_mean"]:.3f} px/step < {fl_min} — region barely moves')
            if fl_max is not None and st['flow_mean'] > float(fl_max):
                ok = False
                r['reasons'].append(f'flow_mean {st["flow_mean"]:.3f} px/step > {fl_max} — runaway motion')
            if not r['moving']:
                r['reasons'].append(
                    f'|v| {st["flow_mean"]:.3f} < coherence floor {floor} — direction is '
                    f'noise here, reversals/net_path REPORTED BUT NOT GATED (a still region '
                    f"is qc_region_flow's freeze gate, not this one)"
                )
            else:
                if rev_max is not None and st['reversals_per_s'] > float(rev_max):
                    ok = False
                    r['reasons'].append(
                        f'{st["reversals_per_s"]:.2f} direction reversals/s > {rev_max} — '
                        f'the motion thrashes back and forth (JITTER), it does not travel'
                    )
                if net_min is not None and st['net_path'] < float(net_min):
                    ok = False
                    r['reasons'].append(
                        f'net/path {st["net_path"]:.3f} < {net_min} — only '
                        f'{st["net_path"] * 100:.0f}% of the distance travelled becomes '
                        f'displacement; the rest cancels itself out (vibration)'
                    )
                if win_min is not None and st['net_path_win'] is not None and st['net_path_win'] < float(win_min):
                    ok = False
                    r['reasons'].append(
                        f'windowed net/path {st["net_path_win"]:.3f} < {win_min} — '
                        f'incoherent inside every ~{_MOTION_WIN_S:g}s window'
                    )
            r['ok'] = bool(ok)
            out['regions'][name] = r
            out['checks'].append(
                {
                    'check': f'motion_quality:{name}',
                    'ok': r['ok'],
                    'reversals_per_s': r['reversals_per_s'],
                    'net_path': r['net_path'],
                    'flow_mean': r['flow_mean'],
                    'note': '; '.join(r['reasons']),
                }
            )
            _win_txt = '' if r['net_path_win'] is None else f' (win {r["net_path_win"]:.3f})'
            _still_txt = '' if r['moving'] else ' [still — coherence not gated]'
            log(
                f'[qc_motion_quality] {name}: |v| {r["flow_mean"]:.3f} '
                f'(med {r["flow_median"]:.3f}) reversals {r["reversals_per_s"]:.2f}/s '
                f'net/path {r["net_path"]:.3f}{_win_txt} -> '
                f'{"PASS" if r["ok"] else "FAIL"}{_still_txt}'
            )
            for rr in r['reasons']:
                log(f'[qc_motion_quality]   {name}: {rr}')
        out['ok'] = all(v.get('ok', True) for v in out['regions'].values())
        # A gate that quietly passes because it read nothing is the failure mode this whole
        # file exists to stop: cv2 opens a missing/undecodable path without raising and
        # every region comes back 'unmeasured'. Stay fail-open, but never stay quiet.
        if out['regions'] and all(v.get('unmeasured') for v in out['regions'].values()):
            out['error'] = (
                'no measurable samples from any region — clip unreadable, too '
                'short, or boxes are degenerate; THIS GATE DID NOT RUN'
            )
            out['reasons'].append(out['error'])
            log(f'[qc_motion_quality] WARNING: {out["error"]}')
    except Exception as e:
        out['error'] = str(e)[:200]
        out['ok'] = bool(fail_open)
        log(f'[qc_motion_quality] ERROR (fail-{"open" if fail_open else "CLOSED"}): {e}')
    _record_qc(out)
    return out


def qc_motion_balance(
    clip_path, pairs, max_ratio=None, regions=None, step=2, log_fn=None, measured=None, fail_open=True
):
    """Limb-vs-face motion balance (2026-07-31) — the second half of "spastic".

    The operator's complaint is not only that the hand jitters; it is that the hand jitters
    while the FACE is dead. Neither is visible to a per-region floor: the face passes
    ("it moved a bit"), the hand passes ("it moved a lot"), and the SHOT still reads wrong,
    because a body whose limb outruns its head by an order of magnitude does not look alive.

    pairs: [(name_a, name_b), ...] — the ratio reported is flow_mean(a) / flow_mean(b), the
    same |mean flow vector| statistic qc_motion_quality reports. regions: {name: box} for
    every name used (not needed if `measured` is passed).
    measured: an existing qc_motion_quality() result to reuse — passing it skips a second
    full decode of the clip (~25s on a 20s 1664x960 deliverable).
    max_ratio: None -> 7.5 (calibrated, see the block header), scalar, or {'a/b': value}
    per pair keyed 'name_a/name_b'.

    Measured a_hand/a_head: v6 (natural) 4.13 PASS, v10 (spastic) 20.50 FAIL. The suggested
    default of 3.0 was rejected on measurement — it false-fails v6 on the production a_head
    box; 7.5 is the value that holds the v6-PASS/v10-FAIL pattern for every face-box
    convention measured (tight-crop faces score v6 1.61-2.50 vs v10 13.42-17.44).

    A pair is only gated when region a is actually MOVING (>= _MOTION_COHERENCE_FLOOR):
    "a jittery limb on a dead face" needs a live limb, and a ratio of two noise readings is
    not evidence. Returns {'ok', 'pairs': {'a/b': {'ratio','flow_a','flow_b','ok','reasons'}},
    'checks': [...]}. Advisory: fail-open on internal error."""
    log = log_fn or (lambda _m: None)
    out = {
        'tag': f'motion_balance:{os.path.basename(clip_path)}',
        'kind': 'motion_balance',
        'path': clip_path,
        'ok': True,
        'pairs': {},
        'checks': [],
        'reasons': [],
    }
    try:
        pairs = [tuple(p) for p in (pairs or []) if p and len(p) == 2]
        if not pairs:
            out['error'] = 'no pairs supplied — nothing to compare'
            _record_qc(out)
            return out
        flows = {}
        if isinstance(measured, dict) and measured.get('regions'):
            flows = {
                k: v.get('flow_mean')
                for k, v in measured['regions'].items()
                if isinstance(v, dict) and v.get('flow_mean') is not None
            }
        need = [n for p in pairs for n in p if n not in flows]
        if need:
            sub = {n: (regions or {})[n] for n in need if n in (regions or {})}
            missing = [n for n in need if n not in sub]
            if missing:
                out['error'] = (
                    f'no box and no measurement for region(s) {sorted(set(missing))} — pass regions= or measured='
                )
                log(f'[qc_motion_balance] {out["error"]}')
                _record_qc(out)
                return out
            fps, vecs, _pp = _region_flow_vectors(clip_path, sub, step=step)
            for n in sub:
                st = _motion_vector_stats(vecs.get(n), fps, step)
                flows[n] = None if st is None else st['flow_mean']
        for a, b in pairs:
            key = f'{a}/{b}'
            fa, fb = flows.get(a), flows.get(b)
            thr = _gate_thr(max_ratio, key, _MOTION_BALANCE_RATIO_MAX)
            p = {
                'flow_a': None if fa is None else round(float(fa), 4),
                'flow_b': None if fb is None else round(float(fb), 4),
                'max_ratio': thr,
                'ok': True,
                'reasons': [],
            }
            if fa is None or fb is None:
                p['reasons'].append('region unmeasurable — pair skipped')
                p['ratio'] = None
            else:
                ratio = float(fa) / max(float(fb), 1e-6)
                p['ratio'] = round(ratio, 3)
                if float(fa) < _MOTION_COHERENCE_FLOOR:
                    p['reasons'].append(
                        f'{a} is still (|v| {fa:.3f} < {_MOTION_COHERENCE_FLOOR}) — '
                        f'no limb motion to be out of balance; not gated'
                    )
                elif thr is not None and ratio > float(thr):
                    p['ok'] = False
                    p['reasons'].append(
                        f'{a} moves {ratio:.1f}x {b} (> {thr}) — a live limb on a dead '
                        f'{b} (|v| {fa:.3f} vs {fb:.3f}); the shot reads puppet-like'
                    )
            out['pairs'][key] = p
            out['checks'].append(
                {'check': f'motion_balance:{key}', 'ok': p['ok'], 'ratio': p['ratio'], 'note': '; '.join(p['reasons'])}
            )
            log(
                f'[qc_motion_balance] {key}: '
                f'{"n/a" if p["ratio"] is None else format(p["ratio"], ".2f") + "x"} '
                f'(|v| {p["flow_a"]} vs {p["flow_b"]}, max {thr}) -> '
                f'{"PASS" if p["ok"] else "FAIL"}'
            )
            for rr in p['reasons']:
                log(f'[qc_motion_balance]   {key}: {rr}')
        out['ok'] = all(v.get('ok', True) for v in out['pairs'].values())
        if out['pairs'] and all(v.get('ratio') is None for v in out['pairs'].values()):
            out['error'] = 'no pair could be measured — clip unreadable or boxes are degenerate; THIS GATE DID NOT RUN'
            out['reasons'].append(out['error'])
            log(f'[qc_motion_balance] WARNING: {out["error"]}')
    except Exception as e:
        out['error'] = str(e)[:200]
        out['ok'] = bool(fail_open)
        log(f'[qc_motion_balance] ERROR (fail-{"open" if fail_open else "CLOSED"}): {e}')
    _record_qc(out)
    return out
