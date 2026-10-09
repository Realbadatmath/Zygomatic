# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import math

from zyg_workflows.vfx_detectors.core import (
    _EPS,
    _ev,
    _mean,
    _std,
    detector,
)

from zyg_workflows.vfx_detectors.picture import (
    _dedupe_runs,
)

# ═══════════════════════════════════════════════════════════════════════════
# FACE  (landmark tier)
# ═══════════════════════════════════════════════════════════════════════════


@detector(
    'face_head.blink',
    unit='EAR',
    threshold_key='blink_ear',
    needs=('face',),
    note='A CLOSE followed by a RE-OPEN within blink_max_frames. The re-open is '
    'required: eyes that shut and stay shut are eyes_closed, not a blink. '
    'The textbook EAR threshold of 0.20 is calibrated on photographs — on a '
    'drawn eye it will be wrong, which is why the best value is reported.',
)
def d_blink(ctx):
    ear, bs = [], []
    for i in range(ctx.n):
        fs = ctx.faces_at(i)
        ear.append(fs[0]['ear_mean'] if fs else None)
        bs.append(max(fs[0]['bs_blink_l'], fs[0]['bs_blink_r']) if fs else None)
    thr_e, thr_b = ctx.T['blink_ear'], ctx.T['blink_bs']
    maxf = int(ctx.T['blink_max_frames'])
    have = [e for e in ear if e is not None]
    best = min(have) if have else 0.0
    closed = []
    for i in range(ctx.n):
        if ear[i] is None:
            closed.append(False)
            continue
        closed.append(ear[i] <= thr_e or (bs[i] is not None and bs[i] >= thr_b))
    events = []
    i = 0
    while i < ctx.n:
        if not closed[i]:
            i += 1
            continue
        j = i
        while j + 1 < ctx.n and closed[j + 1]:
            j += 1
        span = j - i + 1
        reopened = j + 1 < ctx.n and ear[j + 1] is not None and not closed[j + 1]
        if span <= maxf and reopened and i > 0:
            events.append(
                _ev(
                    'face_head.blink',
                    i,
                    ctx,
                    min(1.0, 1.0 - (ear[i] or 0) / max(_EPS, thr_e)),
                    span_frames=span,
                    seconds=round(span / ctx.fps, 3),
                    ear_min=round(min(x for x in ear[i : j + 1] if x is not None), 4),
                    blendshape_max=round(max((x for x in bs[i : j + 1] if x is not None), default=0.0), 4),
                )
            )
        i = j + 1
    return events, round(best, 4)


@detector(
    'face_head.eyes_closed',
    unit='EAR',
    threshold_key='blink_ear',
    needs=('face',),
    note='Eyes shut for LONGER than a blink — a held expression, not a blink.',
)
def d_eyes_closed(ctx):
    thr, maxf = ctx.T['blink_ear'], int(ctx.T['blink_max_frames'])
    ear = [(ctx.faces_at(i)[0]['ear_mean'] if ctx.faces_at(i) else None) for i in range(ctx.n)]
    events, best = [], 1.0
    i = 0
    while i < ctx.n:
        if ear[i] is None or ear[i] > thr:
            i += 1
            continue
        j = i
        while j + 1 < ctx.n and ear[j + 1] is not None and ear[j + 1] <= thr:
            j += 1
        span = j - i + 1
        best = min(best, min(x for x in ear[i : j + 1] if x is not None))
        if span > maxf:
            events.append(_ev('face_head.eyes_closed', i, ctx, 1.0, span_frames=span, seconds=round(span / ctx.fps, 3)))
        i = j + 1
    return events, round(best, 4)


@detector(
    'face_head.lip_movement',
    unit='MAR variance',
    threshold_key='lip_move_var',
    needs=('face',),
    note='Mouth aperture VARIANCE over a rolling window — speech is aperture that '
    'keeps changing. A held open mouth (a shout) has a high MAR and near-zero '
    'variance and is deliberately NOT counted here.',
)
def d_lip(ctx):
    mar = [(ctx.faces_at(i)[0]['mouth_open_norm'] if ctx.faces_at(i) else None) for i in range(ctx.n)]
    jaw = [(ctx.faces_at(i)[0]['bs_jaw_open'] if ctx.faces_at(i) else None) for i in range(ctx.n)]
    w = max(3, int(round(ctx.fps * 0.35)))
    thr = ctx.T['lip_move_var']
    events, best = [], 0.0
    for i in range(0, max(0, ctx.n - w)):
        win = [x for x in mar[i : i + w] if x is not None]
        if len(win) < max(3, w // 2):
            continue
        v = _std(win) ** 2
        best = max(best, v)
        if v >= thr:
            jw = [x for x in jaw[i : i + w] if x is not None]
            events.append(
                _ev(
                    'face_head.lip_movement',
                    i,
                    ctx,
                    min(1.0, v / (thr * 4)),
                    mar_variance=round(v, 6),
                    mar_mean=round(_mean(win), 4),
                    mar_range=round(max(win) - min(win), 4),
                    jaw_open_mean=round(_mean(jw), 4) if jw else None,
                    window=[i, i + w - 1],
                )
            )
    return _dedupe_runs(events, gap=w), round(best, 6)


@detector('face_head.mouth_open', unit='MAR', threshold_key='mouth_open_mar', needs=('face',))
def d_mouth_open(ctx):
    events, best = [], 0.0
    for i in range(ctx.n):
        fs = ctx.faces_at(i)
        if not fs:
            continue
        v = fs[0]['mar']
        best = max(best, v)
        if v >= ctx.T['mouth_open_mar']:
            events.append(
                _ev('face_head.mouth_open', i, ctx, min(1.0, v), mar=round(v, 4), jaw_open=fs[0]['bs_jaw_open'])
            )
    return _dedupe_runs(events), round(best, 4)


@detector(
    'face_head.head_turn',
    unit='deg/s',
    threshold_key='head_turn_deg_per_s',
    needs=('face',),
    note='Yaw rate from the facial transform, differentiated across UNIQUE cels.',
)
def d_head_turn(ctx):
    yaw = [(ctx.faces_at(i)[0]['head_yaw_deg'] if ctx.faces_at(i) else None) for i in range(ctx.n)]
    thr = ctx.T['head_turn_deg_per_s']
    events, best = [], 0.0
    prev_i, prev_v = None, None
    for u in ctx.uidx:
        v = yaw[u] if u < len(yaw) else None
        if v is None:
            continue
        if prev_v is not None:
            dt = max(_EPS, (u - prev_i) / ctx.fps)
            rate = abs(v - prev_v) / dt
            best = max(best, rate)
            if rate >= thr:
                events.append(
                    _ev(
                        'face_head.head_turn',
                        u,
                        ctx,
                        min(1.0, rate / (thr * 3)),
                        yaw_rate_deg_s=round(rate, 2),
                        yaw_from=round(prev_v, 2),
                        yaw_to=round(v, 2),
                    )
                )
        prev_i, prev_v = u, v
    return _dedupe_runs(events), round(best, 2)


# ═══════════════════════════════════════════════════════════════════════════
# BODY ACTION  (landmark tier)
# ═══════════════════════════════════════════════════════════════════════════


def _peaks(ctx, vkey, thr):
    """Frames where a velocity series peaks above thr, with the peak value."""
    out, best = [], 0.0
    for v in ctx.vel:
        val = v.get(vkey)
        if val is None:
            continue
        best = max(best, abs(val))
        if abs(val) >= thr:
            out.append((v['frame'], abs(val), v))
    return out, best


@detector(
    'body_action.kick',
    unit='torso-lengths/s',
    threshold_key='kick_ankle_v',
    needs=('pose',),
    note='An ankle moving fast WHILE its knee extends. Both are required: a fast '
    'ankle with a folded knee is a run cycle, not a kick. Velocity is in '
    'torso-lengths per second so one threshold survives a change of shot size.',
)
def d_kick(ctx):
    thr_v, thr_k = ctx.T['kick_ankle_v'], ctx.T['kick_knee_extend']
    events, best = [], 0.0
    for side in ('l', 'r'):
        peaks, b = _peaks(ctx, f'v_ankle_{side}', thr_v)
        best = max(best, b)
        for frame, val, v in peaks:
            dknee = v.get(f'd_knee_{side}_deg')
            if dknee is None or dknee < thr_k:
                continue
            pose = ctx.pose_at(frame)
            events.append(
                _ev(
                    'body_action.kick',
                    frame,
                    ctx,
                    min(1.0, val / (thr_v * 2)),
                    side=side,
                    ankle_speed=round(val, 3),
                    knee_extension_rate=round(dknee, 1),
                    knee_angle=round(pose.get(f'knee_{side}_deg', 0), 1) if pose else None,
                    ankle_reach=round(pose.get(f'ankle_{side}_reach', 0), 3) if pose else None,
                    deceleration=round(v.get(f'a_ankle_{side}', 0.0), 2),
                )
            )
    return _dedupe_runs(events), round(best, 3)


@detector(
    'body_action.punch',
    unit='torso-lengths/s',
    threshold_key='punch_wrist_v',
    needs=('pose',),
    note='A wrist moving fast WHILE its elbow extends, then decelerating. The '
    'deceleration is what separates a punch from a throw.',
)
def d_punch(ctx):
    thr_v, thr_e = ctx.T['punch_wrist_v'], ctx.T['punch_elbow_extend']
    events, best = [], 0.0
    for side in ('l', 'r'):
        peaks, b = _peaks(ctx, f'v_wrist_{side}', thr_v)
        best = max(best, b)
        for frame, val, v in peaks:
            delb = v.get(f'd_elbow_{side}_deg')
            if delb is None or delb < thr_e:
                continue
            pose = ctx.pose_at(frame)
            events.append(
                _ev(
                    'body_action.punch',
                    frame,
                    ctx,
                    min(1.0, val / (thr_v * 2)),
                    side=side,
                    wrist_speed=round(val, 3),
                    elbow_extension_rate=round(delb, 1),
                    elbow_angle=round(pose.get(f'elbow_{side}_deg', 0), 1) if pose else None,
                    reach=round(pose.get(f'wrist_{side}_reach', 0), 3) if pose else None,
                    deceleration=round(v.get(f'a_wrist_{side}', 0.0), 2),
                )
            )
    return _dedupe_runs(events), round(best, 3)


@detector(
    'body_action.slap',
    unit='torso-lengths/s',
    threshold_key='slap_wrist_v',
    needs=('pose',),
    note='A fast wrist on a LATERAL arc (mostly horizontal travel) with an open '
    'hand where one is visible, ending near another subject. Without a second '
    'subject in frame this cannot separate a slap from a swipe — it says so '
    'in the event.',
)
def d_slap(ctx):
    thr = ctx.T['slap_wrist_v']
    events, best = [], 0.0
    for side in ('l', 'r'):
        peaks, b = _peaks(ctx, f'v_wrist_{side}', thr)
        best = max(best, b)
        for frame, val, v in peaks:
            vx, vy = abs(v.get(f'vx_wrist_{side}', 0.0)), abs(v.get(f'vy_wrist_{side}', 0.0))
            lateral = vx / max(_EPS, vx + vy)
            if lateral < 0.6:
                continue
            hands = ctx.hands_at(frame)
            openness = max((h['openness'] for h in hands), default=None)
            n_faces = len(ctx.faces_at(frame))
            events.append(
                _ev(
                    'body_action.slap',
                    frame,
                    ctx,
                    min(1.0, val / (thr * 2)),
                    side=side,
                    wrist_speed=round(val, 3),
                    lateral_fraction=round(lateral, 3),
                    hand_openness=round(openness, 3) if openness is not None else None,
                    faces_in_frame=n_faces,
                    ambiguity='no second subject in frame — cannot separate a slap from a swipe' if n_faces < 2 else '',
                )
            )
    return _dedupe_runs(events), round(best, 3)


@detector(
    'body_action.jump',
    unit='torso-lengths/s',
    threshold_key='jump_com_v',
    needs=('pose',),
    note='Centre of mass rising fast with BOTH ankles leaving their baseline together.',
)
def d_jump(ctx):
    thr = ctx.T['jump_com_v']
    events, best = [], 0.0
    for v in ctx.vel:
        vy = v.get('vy_com')
        if vy is None:
            continue
        rise = -vy  # image y grows downward
        best = max(best, rise)
        if rise >= thr:
            pose = ctx.pose_at(v['frame'])
            events.append(
                _ev(
                    'body_action.jump',
                    v['frame'],
                    ctx,
                    min(1.0, rise / (thr * 2)),
                    com_rise_speed=round(rise, 3),
                    stance_ratio=round(pose.get('stance_ratio', 0), 3) if pose else None,
                    ankle_l_speed=round(v.get('v_ankle_l', 0.0), 3),
                    ankle_r_speed=round(v.get('v_ankle_r', 0.0), 3),
                )
            )
    return _dedupe_runs(events), round(best, 3)


@detector(
    'body_action.crouch',
    unit='stance ratio',
    threshold_key='crouch_stance',
    needs=('pose',),
    note='Pelvis-to-ankle distance collapsing relative to the torso. Scale-free, so it survives a shot-size change.',
)
def d_crouch(ctx):
    thr = ctx.T['crouch_stance']
    events, best = [], 99.0
    for i in ctx.uidx:
        pose = ctx.pose_at(i)
        if not pose:
            continue
        sr = pose.get('stance_ratio', 99.0)
        best = min(best, sr)
        if sr <= thr:
            events.append(
                _ev(
                    'body_action.crouch',
                    i,
                    ctx,
                    min(1.0, thr / max(_EPS, sr) - 1.0),
                    stance_ratio=round(sr, 3),
                    knee_l=round(pose.get('knee_l_deg', 0), 1),
                    knee_r=round(pose.get('knee_r_deg', 0), 1),
                )
            )
    return _dedupe_runs(events), round(best, 3)


@detector(
    'body_action.gait',
    unit='alternation 0-1',
    threshold_key='gait_alternation',
    needs=('pose',),
    note='Walking/running read as ANTI-CORRELATED ankle speeds: the feet take '
    'turns. Does not separate a walk from a run — that needs a cycle-rate '
    'estimate this does not compute.',
)
def d_gait(ctx):
    la = [v.get('v_ankle_l') for v in ctx.vel]
    ra = [v.get('v_ankle_r') for v in ctx.vel]
    pairs = [(a, b) for a, b in zip(la, ra) if a is not None and b is not None]
    if len(pairs) < 6:
        return [], 0.0
    a = [p[0] for p in pairs]
    b = [p[1] for p in pairs]
    ma, mb = _mean(a), _mean(b)
    sa, sb = _std(a), _std(b)
    if sa < _EPS or sb < _EPS:
        return [], 0.0
    corr = sum((x - ma) * (y - mb) for x, y in pairs) / ((len(pairs) - 1) * sa * sb)
    alt = max(0.0, -corr)
    events = []
    if alt >= ctx.T['gait_alternation']:
        events.append(
            _ev(
                'body_action.gait',
                ctx.vel[0]['frame'],
                ctx,
                min(1.0, alt),
                ankle_anticorrelation=round(alt, 4),
                mean_ankle_speed=round(0.5 * (ma + mb), 3),
                frames=[ctx.vel[0]['frame'], ctx.vel[-1]['frame']],
            )
        )
    return events, round(alt, 4)


@detector(
    'body_action.fall',
    unit='torso-lengths/s',
    threshold_key='fall_com_v',
    needs=('pose',),
    note='Centre of mass dropping fast while the torso rotates away from upright.',
)
def d_fall(ctx):
    thr = ctx.T['fall_com_v']
    events, best = [], 0.0
    for v in ctx.vel:
        vy = v.get('vy_com')
        if vy is None or vy <= 0:
            continue
        best = max(best, vy)
        lean = abs(v.get('d_torso_lean_deg', 0.0))
        if vy >= thr and lean > 30:
            pose = ctx.pose_at(v['frame'])
            events.append(
                _ev(
                    'body_action.fall',
                    v['frame'],
                    ctx,
                    min(1.0, vy / (thr * 2)),
                    com_fall_speed=round(vy, 3),
                    lean_rate=round(lean, 1),
                    torso_lean=round(pose.get('torso_lean_deg', 0), 1) if pose else None,
                )
            )
    return _dedupe_runs(events), round(best, 3)


# ═══════════════════════════════════════════════════════════════════════════
# HANDS / MANIPULATION
# ═══════════════════════════════════════════════════════════════════════════


@detector(
    'hand_object.hand_to_mouth',
    unit='normalised distance',
    threshold_key='hand_mouth_dist',
    needs=('pose', 'face'),
    note='A wrist arriving within hand_mouth_dist face-widths of the mouth and '
    'DWELLING there. Covers smoking, drinking, eating and covering the mouth '
    'alike — it measures the trajectory, NOT the object, so it cannot say '
    'which. Naming the object needs the VLM pass.',
)
def d_hand_mouth(ctx):
    thr = ctx.T['hand_mouth_dist']
    events, best = [], 9.0
    for i in ctx.uidx:
        pose, faces = ctx.pose_at(i), ctx.faces_at(i)
        if not pose or not faces:
            continue
        f = faces[0]
        mouth = (f['centre'][0], f['centre'][1] + 0.25 * f['bbox']['h'])
        fw = max(_EPS, f['face_w'])
        for side in ('l', 'r'):
            w = pose.get(f'wrist_{side}')
            if not w:
                continue
            d = math.hypot(w[0] - mouth[0], w[1] - mouth[1]) / fw
            best = min(best, d)
            if d <= thr:
                v = ctx.vel_at(i)
                events.append(
                    _ev(
                        'hand_object.hand_to_mouth',
                        i,
                        ctx,
                        min(1.0, thr / max(_EPS, d) - 1.0),
                        side=side,
                        distance_facewidths=round(d, 4),
                        wrist_speed=round(v.get(f'v_wrist_{side}', 0.0), 3),
                        object='UNIDENTIFIED — trajectory only; enable the VLM pass to name what is in the hand',
                    )
                )
    return _dedupe_runs(events), round(best, 4)


@detector(
    'hand_object.pinch_grasp',
    unit='aperture (palm-lengths)',
    threshold_key='pinch_aperture',
    needs=('hand',),
    note='Thumb-tip to index-tip distance in palm-lengths. A precision grip on a '
    'small object — a cigarette, a page corner, a button — but the object '
    'itself is not detected.',
)
def d_pinch(ctx):
    thr = ctx.T['pinch_aperture']
    events, best = [], 9.0
    for i in range(ctx.n):
        for h in ctx.hands_at(i):
            a = h['pinch_aperture']
            best = min(best, a)
            if a <= thr:
                events.append(
                    _ev(
                        'hand_object.pinch_grasp',
                        i,
                        ctx,
                        min(1.0, thr / max(_EPS, a) - 1.0),
                        side=h.get('side', ''),
                        aperture=round(a, 4),
                        openness=round(h['openness'], 4),
                        bbox=[h['bbox']['x'], h['bbox']['y'], h['bbox']['w'], h['bbox']['h']],
                    )
                )
    return _dedupe_runs(events), round(best, 4)


@detector(
    'hand_object.pointing',
    unit='index extension',
    threshold_key='point_extension',
    needs=('hand',),
    note='Index extended well beyond the other fingers.',
)
def d_point(ctx):
    thr = ctx.T['point_extension']
    events, best = [], 0.0
    for i in range(ctx.n):
        for h in ctx.hands_at(i):
            ext = h.get('finger_extension') or []
            if len(ext) < 5:
                continue
            index, others = ext[1], [ext[0], ext[2], ext[3], ext[4]]
            margin = index - _mean(others)
            best = max(best, margin)
            if index >= thr and margin > 0.25:
                events.append(
                    _ev(
                        'hand_object.pointing',
                        i,
                        ctx,
                        min(1.0, margin),
                        side=h.get('side', ''),
                        index_extension=round(index, 4),
                        others_mean=round(_mean(others), 4),
                        margin=round(margin, 4),
                    )
                )
    return _dedupe_runs(events), round(best, 4)


@detector(
    'hand_object.press_contact',
    unit='px/s at contact',
    threshold_key='contact_dist',
    needs=('hand',),
    note='An extended index finger that DECELERATES to a stop and holds — the '
    'kinematic signature shared by pushing a phone button, a doorbell and a '
    'light switch. It cannot see the button. Which surface was pressed needs '
    'object detection this install does not have.',
)
def d_press(ctx):
    events, best = [], 0.0
    tips = {}
    for i in ctx.uidx:
        hs = ctx.hands_at(i)
        if hs:
            tips[i] = hs[0]['index_tip']
    ks = sorted(tips)
    for a, b, c in zip(ks, ks[1:], ks[2:]):
        p0, p1, p2 = tips[a], tips[b], tips[c]
        dt1 = max(_EPS, (b - a) / ctx.fps)
        dt2 = max(_EPS, (c - b) / ctx.fps)
        v1 = math.hypot(p1[0] - p0[0], p1[1] - p0[1]) / dt1
        v2 = math.hypot(p2[0] - p1[0], p2[1] - p1[1]) / dt2
        decel = v1 - v2
        best = max(best, decel)
        if v1 > 0.35 and v2 < 0.06 and decel > 0.3:
            ext = (ctx.hands_at(b) or [{}])[0].get('finger_extension') or []
            if len(ext) >= 2 and ext[1] < 0.9:
                continue
            events.append(
                _ev(
                    'hand_object.press_contact',
                    b,
                    ctx,
                    min(1.0, decel),
                    approach_speed=round(v1, 4),
                    settled_speed=round(v2, 4),
                    deceleration=round(decel, 4),
                    target='UNIDENTIFIED — no object detector; the surface pressed is not measured',
                )
            )
    return _dedupe_runs(events), round(best, 4)


# ═══════════════════════════════════════════════════════════════════════════
# INTERACTION
# ═══════════════════════════════════════════════════════════════════════════


@detector(
    'interaction_social.proximity',
    unit='torso-lengths',
    threshold_key='proximity_torsos',
    needs=('face',),
    note='Two or more faces within proximity_torsos face-widths. '
    'Frame-relative distance, not world distance — two people '
    'at different depths can read as close.',
)
def d_prox(ctx):
    thr = ctx.T['proximity_torsos']
    events, best = [], 99.0
    for i in ctx.uidx:
        fs = ctx.faces_at(i)
        if len(fs) < 2:
            continue
        for a in range(len(fs)):
            for b in range(a + 1, len(fs)):
                fa, fb = fs[a], fs[b]
                unit = max(_EPS, 0.5 * (fa['face_w'] + fb['face_w']))
                d = math.hypot(fa['centre'][0] - fb['centre'][0], fa['centre'][1] - fb['centre'][1]) / unit
                best = min(best, d)
                if d <= thr:
                    events.append(
                        _ev(
                            'interaction_social.proximity',
                            i,
                            ctx,
                            min(1.0, thr / max(_EPS, d) - 1.0),
                            distance_facewidths=round(d, 3),
                            n_faces=len(fs),
                            caveat='frame-relative; depth is not measured',
                        )
                    )
    return _dedupe_runs(events), round(best, 3)
