# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""anny_fit.py — the in-house parametric body fit, v2 (2026-08-04).

RUN:
    python3 -m zyg_workflows.geom.anny_fit <char_id> [--cells ...] [--char-asset char_abel]

WHY THIS FITTER EXISTS. Every published image->mesh regressor is non-commercial (verified
2026-08-04, all of them — including Multi-HMR's SMPL-free Anny checkpoint). The models are
finally clean — Anny is Apache-2.0 code + CC0 data, differentiable — so the image->
parameters step is an optimisation written here, not a network.

V2 FIXES THREE MEASURED FAILURES OF V1 (all found by analysing its own output):

  FIT MODES     v1 fitted a FULL body to anything with >=8 keypoints, and 8 face/shoulder
                points cannot constrain a body's scale or depth: cell_31 exploded to
                276.8px error — a torso the size of the frame, drawn confidently. v2
                triages: full mode needs hips AND knees confidently visible; otherwise
                upper mode fits only the observed chain (head/neck/shoulders/arms) and
                records a draw limit so nothing below the evidence is ever rendered;
                otherwise it DECLINES. Declining is a result.

  YAW SEEDING   v1 started at zero yaw, and an orthographic fit cannot DISCOVER a profile
                from near-collinear 2D points — cell_28 fitted a frontal body beside a
                profile character (97.5px). v2 estimates yaw from the BlazePose shoulder
                z-difference (a signal v1 threw away; now stored as body_z) and races
                stage 1 from four seeds — 0, +-yaw_est, pi — keeping the best.

  ARM PRIOR     with no wrist/elbow targets, v1's L2 regulariser held unobserved arms at
                the MakeHuman REST pose, which is arms-out T-pose: cell_00 drew a giant
                arm across the sky (56.9px). v2 adds weak SYNTHETIC targets for missing
                elbows/wrists — arms hanging at the sides, anchored to shoulder and hip —
                at 0.15 weight, so real detections always dominate but the default is a
                person standing, not a scarecrow. Synthetic points are excluded from the
                reported error: the metric grades the fit against EVIDENCE, never against
                our own prior.

Phenotype stays an INPUT (declared build, calibrated by geom.phenotype), never fitted —
monocular keypoints cannot tell a short adult from a child, and the optimiser must not be
allowed to "discover" a body the bible already declares.
"""

import argparse
import glob
import json
import os
import sys
import time

import numpy as np

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None

from .char_mesh import OUT_ROOT

BLAZE_TO_COCO = [
    'nose',
    'left_eye',
    'right_eye',
    'left_ear',
    'right_ear',
    'left_shoulder',
    'right_shoulder',
    'left_elbow',
    'right_elbow',
    'left_wrist',
    'right_wrist',
    'left_hip',
    'right_hip',
    'left_knee',
    'right_knee',
    'left_ankle',
    'right_ankle',
]
UPPER = (
    'nose',
    'left_eye',
    'right_eye',
    'left_ear',
    'right_ear',
    'left_shoulder',
    'right_shoulder',
    'left_elbow',
    'right_elbow',
    'left_wrist',
    'right_wrist',
)

POSE_BONES_FULL = (
    'upperarm',
    'lowerarm',
    'thigh',
    'shin',
    'shoulder',
    'spine',
    'neck',
    'head',
    'foot',
    'clavicle',
    'root',
    'pelvis',
    'hips',
)
POSE_BONES_UPPER = ('upperarm', 'lowerarm', 'shoulder', 'spine', 'neck', 'head', 'clavicle', 'root')

# 0.15 lost the fight on portraits: the stage-2 regulariser pulls toward REST — which is
# T-pose — and four weak synthetic points could not overcome it (cell_00 still drew the
# arm across the sky at 0.15). 0.45 wins that fight while real detections (weight 1.0)
# still dominate wherever they exist. The reported error still excludes synthetics.
SYNTH_WEIGHT = 0.45
GATE_ERR_OVER_TORSO = 0.08  # above this the fit failed and must not be drawn

# ---------------------------------------------------------------------------------
# CERVICAL PRIOR — where head rotation is allowed to sit in the neck.
#
# THE DEFECT, MEASURED 2026-08-08. t5_joint_rom failed on 44 of 44 fitted poses for abel
# and 43 of 43 for cornelis — a violation rate of exactly 1.0000, whose worst sub-check
# was occiput_c2_share_yaw. That is not the vacuous-denominator artefact it looks like:
# binned by how much rotation was actually being apportioned, 35 of the 44 failures sit
# at 15 degrees or more of real cervical yaw and NONE below 1 degree. The share itself
# reached 0.084 at worst against the >= 0.50 that HeadNeck p.171 prints.
#
# THE CAUSE IS THIS FILE'S OWN REGULARISER, and it is not a bug so much as an omission.
# Stage 2 adds `0.6 * (paa ** 2).mean() * 1000`, a UNIFORM L2 toward rest over every
# bone. Minimising the sum of squares subject to a required total rotation gives an EQUAL
# split, so four cervical joints each take about a quarter. Measured over abel's 44 cells,
# mean |rotation| per joint is neck01 14.31, neck02 11.49, neck03 11.20, head 15.05 deg,
# and the head bone's share of total cervical rotation is mean 0.2797 / median 0.2619 —
# an even four-way split, exactly as the uniform penalty predicts, against an anatomical
# floor of 0.50. The optimiser was never told the neck is not a uniform chain.
#
# THE FIX IS THE RECIPROCAL OF THE TARGET SHARE, and that is an identity rather than a
# tuning. For a weighted penalty sum(w_i * t_i^2) subject to sum(t_i) = T, the minimiser
# is t_i proportional to 1/w_i. So choosing w_i proportional to 1/s_i makes the penalty's
# preferred distribution EXACTLY the shares s_i — no constant to sweep, no threshold to
# move, and the number comes from the gate rather than from here (OCCIPUT_C2_MIN_SHARE,
# sourced to HeadNeck p.171 and adjudicated in geom.anthro.gates).
#
# It is a PRIOR, not a constraint. It reshapes the optimiser's preference in the null
# space that the keypoints leave underdetermined; where the evidence actually pins a
# joint, the evidence still wins, exactly as the arm prior above works. And the reported
# fit error is unchanged in kind: it is still taken over real detections only, so this
# prior cannot grade itself.
CERVICAL_BONES = ('neck01', 'neck02', 'neck03', 'head')
# The rig's top cervical joint. pose_limits.CERVICAL_MAPPING_NOTE establishes by
# MEASUREMENT (head bone head at z=0.7108 on the neutral, against neck03 at 0.6814) that
# the head bone is the occiput-C2 complex, which is the joint HeadNeck p.171 is about.
CERVICAL_OCCIPUT_BONE = 'head'

_MODEL = None


def _model():
    global _MODEL
    if _MODEL is None:
        from anny import create_fullbody_model

        _MODEL = create_fullbody_model()
    return _MODEL


def _rotmat(axis_angle):
    """Batched axis-angle -> rotation matrix (Rodrigues), differentiable."""
    import torch

    theta = torch.linalg.norm(axis_angle, dim=-1, keepdim=True).clamp(min=1e-8)
    k = axis_angle / theta
    K = torch.zeros(axis_angle.shape[:-1] + (3, 3), dtype=axis_angle.dtype)
    K[..., 0, 1], K[..., 0, 2] = -k[..., 2], k[..., 1]
    K[..., 1, 0], K[..., 1, 2] = k[..., 2], -k[..., 0]
    K[..., 2, 0], K[..., 2, 1] = -k[..., 1], k[..., 0]
    eye = torch.eye(3, dtype=axis_angle.dtype).expand_as(K)
    s, c = torch.sin(theta)[..., None], torch.cos(theta)[..., None]
    return eye + s * K + (1 - c) * (K @ K)


def _cervical_reg_weights(bone_names, n_bones):
    """Per-bone multiplier on the stage-2 L2-toward-rest. 1.0 everywhere but the neck.

    Returns (weights (n_bones,) float64 tensor, note dict). The weights are the RECIPROCAL
    of each cervical joint's target share, normalised so the mean weight over the four
    cervical bones is 1.0 — that last part matters: it changes only how the penalty
    DISTRIBUTES rotation within the neck, never how hard it pulls the neck toward rest
    overall, so this cannot be a stealth change to the regularisation strength.

    Falls back to all-ones, with the reason recorded, if the rig does not name the four
    joints this is written against. A prior that silently applied to the wrong bones would
    be worse than no prior.
    """
    import torch

    w = torch.ones(n_bones, dtype=torch.float64)
    note = {'applied': False, 'why': None, 'weights': {}}
    if not bone_names:
        note['why'] = 'this rig exposes no bone names, so the neck cannot be identified'
        return w, note
    try:
        from zyg_workflows.geom import pose_limits as PL

        floor = float(PL.OCCIPUT_C2_MIN_SHARE)
        source = PL.OCCIPUT_SOURCE
    except Exception as e:  # noqa: BLE001
        note['why'] = (
            'geom.pose_limits did not import (%s), so the share floor this prior exists to serve is unavailable' % e
        )
        return w, note

    lower = [nm.lower() for nm in bone_names]
    idx = {}
    for b in CERVICAL_BONES:
        hits = [i for i, nm in enumerate(lower) if nm == b or nm.startswith(b + '.')]
        if not hits:
            note['why'] = (
                'this rig has no bone %r; the cervical prior is written against the four-joint MakeHuman neck' % b
            )
            return w, note
        idx[b] = hits

    # target shares: the occiput complex takes the printed floor, the rest split evenly
    n_lower = len(CERVICAL_BONES) - 1
    share = {b: ((1.0 - floor) / n_lower if b != CERVICAL_OCCIPUT_BONE else floor) for b in CERVICAL_BONES}
    raw = {b: 1.0 / share[b] for b in CERVICAL_BONES}
    scale = len(CERVICAL_BONES) / sum(raw.values())
    for b in CERVICAL_BONES:
        val = raw[b] * scale
        for i in idx[b]:
            w[i] = val
        note['weights'][b] = round(float(val), 6)
    note.update(
        {
            'applied': True,
            'occiput_share_floor': floor,
            'source': source,
            'target_shares': {b: round(share[b], 6) for b in CERVICAL_BONES},
            'rule': 'weight proportional to 1/target_share, normalised to mean 1 '
            'over the cervical bones; the minimiser of sum(w t^2) at fixed '
            'total is t proportional to 1/w, so the preferred distribution '
            'IS the target shares',
        }
    )
    return w, note


def _pose44(pose):
    """axis-angle per bone -> the (1,N,4,4) float64 delta transforms forward() expects.
    Module-level because anny_animate interpolates poses and needs the same encoding."""
    import torch

    R = _rotmat(pose).to(torch.float64)
    T = torch.eye(4, dtype=torch.float64).repeat(len(R), 1, 1)
    T[:, :3, :3] = R
    return T[None]


def _yaw_seeds(b, bz, face_yaw=None):
    """Candidate global yaws: shoulder-z estimate, the HEAD's measured yaw (facial
    transformation matrix — the only reliable profile signal; the matrix underestimates
    at extremes, ~-56deg for a true profile, but a seed only has to be in the right
    basin), and the cardinals as backstop. Deduplicated within 0.15 rad."""
    import math

    cands = [0.0, math.pi]
    if bz is not None:
        from . import keypoints as K

        ls, rs = K.P['left_shoulder'], K.P['right_shoulder']
        dx = float(b[ls, 0] - b[rs, 0])
        dz = float(bz[ls] - bz[rs])
        cands += [math.atan2(dz, dx if abs(dx) > 1e-3 else 1e-3)]
        cands += [-cands[-1]]
    else:
        cands += [math.pi / 2, -math.pi / 2]
    if face_yaw is not None:
        # the matrix reads ~0.62x true yaw at extremes; seed both raw and rescaled
        cands += [face_yaw, -face_yaw, face_yaw * 1.6, -face_yaw * 1.6]
    out = []
    for c in cands:
        if all(abs(c - o) > 0.15 for o in out):
            out.append(c)
    return out[:6]


def fit_cell(cell_dir, iters1=200, iters2=450, phenotype_kwargs=None, body=None, log=print):
    """Fit Anny to one processed cell. Returns the report dict (ok=False = declined).

    `body` is a body SPEC from geom.phenotype (registry_body / spec_for) — the
    registered character's phenotype, local morphs and bone scales, hash-checked
    against the issued cage. It supersedes `phenotype_kwargs`, which is the legacy
    three-number declared-build path and is kept only for the A/B comparison.
    """
    import torch
    from anny.keypoints import KeypointsRegressor
    from . import keypoints as K

    with open(os.path.join(cell_dir, 'mesh.json')) as f:
        mesh = json.load(f)
    name = os.path.basename(cell_dir)
    # a cell whose source image is gone (drift-quarantined, deleted) is out of the
    # corpus — declining beats crashing the batch on imread(None), which is exactly
    # what took down the first v2.1 run when it met the quarantined cells' stale dirs
    if not os.path.exists(mesh.get('image', '')):
        return {'cell': name, 'ok': False, 'reason': 'source image missing (quarantined?)'}
    if not mesh.get('body'):
        return {'cell': name, 'ok': False, 'reason': 'no body'}
    W, H = mesh['size']
    b = np.asarray(mesh['body_landmarks'], np.float32)
    bz = np.asarray(mesh['body_z'], np.float32) if mesh.get('body_z') else None

    # MediaPipe's "visibility" is a PRESENCE estimate, not an in-frame guarantee: on
    # cell_00 it reported the right wrist at 0.73 visibility, 108px BELOW the image.
    # Treating that as evidence pulled an arm toward a point that does not exist in the
    # picture, and the fold-over-the-top arm was the optimiser's route there. Evidence
    # must be visible AND on the canvas.
    def _eff(n):
        x, y, v = b[K.P[n]]
        return float(v) if (0 <= x < W and 0 <= y < H) else 0.0

    vis = {n: _eff(n) for n in BLAZE_TO_COCO}

    # ── triage: what can this image support? ────────────────────────────────
    full_ok = all(vis[n] >= 0.5 for n in ('left_hip', 'right_hip', 'left_knee', 'right_knee'))
    n_upper = sum(1 for n in UPPER if vis[n] >= 0.5)
    if full_ok:
        mode, use_names, bones = 'full', BLAZE_TO_COCO, POSE_BONES_FULL
    elif n_upper >= 6 and vis['left_shoulder'] >= 0.5 and vis['right_shoulder'] >= 0.5:
        mode, use_names, bones = 'upper', UPPER, POSE_BONES_UPPER
    else:
        return {
            'cell': name,
            'ok': False,
            'reason': 'insufficient evidence (upper kps %d) — declining beats inventing' % n_upper,
        }

    sw = float(np.linalg.norm(b[K.P['left_shoulder'], :2] - b[K.P['right_shoulder'], :2])) or 60.0

    tgt, labels, weights = [], [], []
    for n in use_names:
        if vis[n] >= 0.5:
            tgt.append(list(b[K.P[n], :2]))
            labels.append(n)
            weights.append(1.0)
    # synthetic arms-down targets for missing elbows/wrists (the T-pose killer)
    for side in ('left', 'right'):
        sh = b[K.P['%s_shoulder' % side], :2]
        hip = b[K.P['%s_hip' % side], :2] if vis['%s_hip' % side] >= 0.5 else sh + np.array([0.0, 1.9 * sw], np.float32)
        for joint, f in (('elbow', 0.45), ('wrist', 0.95)):
            nm = '%s_%s' % (side, joint)
            if vis[nm] < 0.5 and nm in use_names:
                tgt.append(list(sh + (hip - sh) * f))
                labels.append(nm)
                weights.append(SYNTH_WEIGHT)
    n_real = sum(1 for w in weights if w >= 1.0)
    if n_real < 6:
        return {'cell': name, 'ok': False, 'reason': 'only %d real targets' % n_real}

    tgt_t = torch.tensor(np.array(tgt, np.float32))
    w_t = torch.tensor(np.array(weights, np.float32))[:, None]
    real_mask = torch.tensor([w >= 1.0 for w in weights])

    from . import phenotype as PH

    spec = body if isinstance(body, dict) else (PH.registry_body(PH.resolve_body_name(body), log=log) if body else None)
    if spec is None:
        spec = PH.legacy_spec(phenotype_kwargs, why='phenotype_kwargs= (legacy)')
    # A registry body must be driven through the local_changes='all' model, or its
    # local morphs are ignored in silence; body_model picks the right one.
    m = PH.body_model(spec)
    S44 = PH.bone_scale_matrix(spec, m)
    kr = KeypointsRegressor(m, labels=labels).double()

    if mode == 'full':
        hips_mid = (b[K.P['left_hip'], :2] + b[K.P['right_hip'], :2]) / 2
        sh_mid = (b[K.P['left_shoulder'], :2] + b[K.P['right_shoulder'], :2]) / 2
        torso_px = float(np.linalg.norm(sh_mid - hips_mid)) or 100.0
    else:
        torso_px = 1.6 * sw  # hips unseen — shoulder-width proxy

    # ── PINHOLE CAMERA (v2.1) ───────────────────────────────────────────────
    # Orthographic projection has no concept of distance, so on a close portrait the
    # head/torso projection ratio was systematically wrong (the mesh head ran large).
    # Pinhole: x = f*X/(Z+tz)+cx. f is FIXED at 1.35*max(W,H) — a normal-lens field of
    # view — because f and tz are degenerate through a monocular fit; tz carries scale.
    # tz is initialised from the model's OWN shoulder width in metres (regressed off the
    # phenotyped rest mesh) against the detected shoulder width in pixels — real
    # anthropometry, not a magic constant.
    F_PX = 1.35 * max(W, H)
    with torch.no_grad():
        kr_sh = KeypointsRegressor(m, labels=['left_shoulder', 'right_shoulder']).double()
        rest_out = m(**PH.forward_kwargs(spec, None, model=m, scale44=S44))
        sh3 = kr_sh({'vertices': rest_out['rest_vertices']})[0].numpy()
    shoulder_m = float(np.linalg.norm(sh3[0] - sh3[1])) or 0.35
    tz0 = max(0.6, F_PX * shoulder_m / max(sw, 20.0))

    # THIS READ WAS BROKEN AND SILENTLY SO, fixed 2026-08-08. It tested only `bones`;
    # this anny build exposes the roster as `bone_labels` and has no `bones` attribute at
    # all, so bone_names came back EMPTY on every fit ever run through this file. Two
    # things depended on it and both were quietly inert:
    #   * `allow` fell through to its all-ones fallback, so POSE_BONES_FULL and
    #     POSE_BONES_UPPER restricted nothing and all 163 bones were free parameters —
    #     fingers, toes and face bones included — in a fit driven by 17 body keypoints.
    #   * the cervical prior below could not identify the neck and declined itself.
    # mesh_skeletons._bone_names already accepted either attribute; this now uses it, so
    # there is one accessor and a rig exposing neither fails loudly instead of silently
    # disabling two features.
    from zyg_workflows.geom.mesh_skeletons import _bone_names as _bn

    bone_names = [str(n) for n in _bn(m)]
    n_bones = len(m().get('rest_bone_heads')[0])
    allow = (
        torch.tensor([any(s in nm.lower() for s in bones) for nm in bone_names])
        if bone_names
        else torch.ones(n_bones, dtype=torch.bool)
    )
    reg_w, reg_note = _cervical_reg_weights(bone_names, n_bones)
    reg_w2 = reg_w.to(torch.float32)[:, None]

    def make_params(yaw):
        cam = torch.tensor([tz0, W / 2.0, H / 2.0], requires_grad=True)
        gaa = torch.tensor([0.0, 0.0, float(yaw)], requires_grad=True)
        paa = torch.zeros(n_bones, 3, requires_grad=True)
        return [cam, gaa, paa]

    def project(cam, gaa, paa, stage):
        pose = paa * allow[:, None] if stage >= 2 else torch.zeros_like(paa)
        out = m(**PH.forward_kwargs(spec, pose, model=m, scale44=S44))
        kp3 = kr(out)[0].to(torch.float32)
        p = kp3 @ _rotmat(gaa).T
        z = (p[:, 1] + cam[0]).clamp(min=0.25)
        x = F_PX * p[:, 0] / z + cam[1]
        y = F_PX * (-p[:, 2]) / z + cam[2]
        return torch.stack([x, y], -1)

    def optimise(params, stage, iters, lr, yaw_anchor=None):
        opt = torch.optim.Adam(params, lr=lr)
        loss = None
        for _ in range(iters):
            opt.zero_grad()
            pr = project(params[0], params[1], params[2], stage)
            loss = (torch.nn.functional.smooth_l1_loss(pr, tgt_t, beta=8.0, reduction='none') * w_t).mean()
            if stage == 2:
                # reg_w2 is 1.0 for every bone but the four cervical joints, and its mean
                # over those four is 1.0, so the overall pull toward rest is unchanged and
                # only its distribution WITHIN the neck moves. See _cervical_reg_weights.
                loss = loss + 0.6 * ((params[2] ** 2) * reg_w2).mean() * 1000
            # upper mode: the head IS most of the evidence, so the body may not spin
            # away from the measured head yaw (soft — evidence can still move it)
            if yaw_anchor is not None:
                loss = loss + 25.0 * (params[1][2] - yaw_anchor) ** 2
            loss.backward()
            opt.step()
            with torch.no_grad():
                params[0][0].clamp_(min=0.3)
        return float(loss)

    t0 = time.time()
    face_yaw = mesh.get('face_yaw')
    # THE SEED RACE MUST INCLUDE A SHORT STAGE 2. Shoulders and eyes are left-right
    # symmetric, so at stage 1 (rest pose, rigid) a frontal body and a MIRRORED one score
    # nearly identically — sixty stage-2 iterations per seed let the arms break the tie
    # before the winner is chosen.
    best = None
    for yaw in _yaw_seeds(b, bz, face_yaw):
        params = make_params(yaw)
        anchor = float(yaw) if (mode == 'upper' and face_yaw is not None) else None
        optimise(params, 1, max(80, iters1 // 2), 0.05, yaw_anchor=anchor)
        l2 = optimise(params, 2, 60, 0.03, yaw_anchor=anchor)
        if best is None or l2 < best[0]:
            best = (l2, params, yaw)
    _, params, seed_yaw = best
    cam, gaa, paa = params
    anchor = float(seed_yaw) if (mode == 'upper' and face_yaw is not None) else None
    optimise(params, 1, iters1 // 2, 0.03, yaw_anchor=anchor)
    optimise(params, 2, iters2, 0.02, yaw_anchor=anchor)

    with torch.no_grad():
        pr = project(cam, gaa, paa, 2)
        # error over REAL evidence only — the prior must not grade itself
        err = float(torch.linalg.norm((pr - tgt_t)[real_mask], dim=-1).mean())
    eot = err / torso_px
    ok_fit = eot <= GATE_ERR_OVER_TORSO
    log(
        '  %s [%s] seed_yaw=%+.2f err=%.1fpx (%.3f torso) %s'
        % (name, mode, seed_yaw, err, eot, 'OK' if ok_fit else 'GATED')
    )

    # ── artifacts ───────────────────────────────────────────────────────────
    with torch.no_grad():
        pose = paa * allow[:, None]
        out = m(**PH.forward_kwargs(spec, pose, model=m, scale44=S44))
        v = out['vertices'][0].to(torch.float32) @ _rotmat(gaa).T
        vx = (v[:, 0] * cam[0] + cam[1]).numpy()
        vy = (-v[:, 2] * cam[0] + cam[2]).numpy()
    img = cv2.imread(mesh['image'])
    for x, y in zip(vx[::6], vy[::6]):
        if 0 <= int(x) < W and 0 <= int(y) < H:
            cv2.circle(img, (int(x), int(y)), 1, (80, 255, 130), -1)
    prn = pr.numpy()
    for i, ((x, y), (tx_, ty_)) in enumerate(zip(prn, np.array(tgt))):
        col = (0, 80, 255) if weights[i] >= 1.0 else (160, 160, 160)
        cv2.circle(img, (int(x), int(y)), 5, col, 2)
        cv2.line(img, (int(x), int(y)), (int(tx_), int(ty_)), (0, 200, 255), 1)
    cv2.imwrite(os.path.join(cell_dir, 'anny_fit.png'), img)

    real_ys = [t[1] for t, w in zip(tgt, weights) if w >= 1.0]
    rep = {
        'cell': name,
        'ok': True,
        'fit_ok': ok_fit,
        'fit_mode': mode,
        'keypoints_used': n_real,
        'synthetic_targets': len(tgt) - n_real,
        'seed_yaw': round(float(seed_yaw), 3),
        'mean_err_px': round(err, 2),
        'err_over_torso': round(eot, 4),
        'gate_threshold': GATE_ERR_OVER_TORSO,
        # upper fits may only be drawn down to the evidence, plus a small margin
        'draw_limit_y': (None if mode == 'full' else round(float(max(real_ys) + 0.45 * sw), 1)),
        'seconds': round(time.time() - t0, 1),
        'phenotype': {k: round(float(v_), 4) for k, v_ in (spec.get('phenotype_kwargs') or {}).items()},
        # THE BODY THIS FIT ACTUALLY USED, recorded in full. Before 2026-09-02 the
        # report carried three phenotype numbers and nothing else, so a plate built
        # from a fit could not tell whether it had the registered character's body or
        # a height-only calibration of a declared age — and for 35 of abel's 44 cells
        # it had neither, because phenotype_kwargs was None.
        'body': {
            'source': spec.get('source'),
            'name': spec.get('name'),
            'cage_vert_sha256': spec.get('cage_vert_sha256_rebuilt'),
            'hash_verified': bool(spec.get('hash_verified')),
            'local_changes': spec.get('local_changes') or {},
            'bone_scales_effective': spec.get('bone_scales_effective') or {},
            'anatomy_layer': spec.get('anatomy_layer') or {},
            'anatomy_layer_applied': False,
            'describe': PH.describe(spec),
        },
        'cervical_prior': reg_note,
        'camera_model': 'pinhole',
        'camera': [round(float(F_PX), 2)] + [round(float(x), 4) for x in cam.detach()],
        'global_aa': [round(float(x), 4) for x in gaa.detach()],
        'pose_aa': [[round(float(v_), 5) for v_ in row] for row in (paa * allow[:, None]).detach()],
    }
    with open(os.path.join(cell_dir, 'anny_fit.json'), 'w') as f:
        json.dump(rep, f, indent=1)
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('char_id')
    ap.add_argument('--cells', default='')
    ap.add_argument('--char-asset', default='')
    ap.add_argument(
        '--body',
        default='',
        help='registered body to fit WITH (registry name, char_id or asset '
        'name). Rebuilds the issued recipe — phenotype, local morphs, '
        'bone scales and the recorded phalanx correction — and refuses '
        'if the rebuilt cage does not hash to the registry value.',
    )
    ap.add_argument(
        '--legacy-phenotype',
        action='store_true',
        help='the pre-2026-09-02 path: height-only calibration of the '
        'declared age from --char-asset, no locals, no bone scales. '
        'Kept for the A/B comparison only.',
    )
    ap.add_argument(
        '--out-name',
        default='anny_fit.json',
        help='report filename inside each cell dir; use this to keep a '
        'legacy run beside a registry run instead of replacing it',
    )
    a = ap.parse_args(argv)
    if a.body and a.legacy_phenotype:
        raise SystemExit(
            '--body and --legacy-phenotype are two different bodies; pick '
            'one. Run twice with different --out-name to compare them.'
        )
    root = os.path.join(OUT_ROOT, a.char_id)
    dirs = [os.path.join(root, c.strip()) for c in a.cells.split(',') if c.strip()] or sorted(
        glob.glob(os.path.join(root, 'cell_*'))
    )
    from . import phenotype as P

    body = a.body
    if not body and not a.legacy_phenotype:
        # DEFAULT CHANGED 2026-09-02: a char_id that names a registered body now fits
        # with that body. The old default built a three-number calibration (or, when
        # --char-asset was omitted, the anny DEFAULT ADULT FEMALE) and called it the
        # character. Falling back is still allowed, but it is announced.
        body = P.resolve_body_name(a.char_id) or P.resolve_body_name(a.char_asset)
        if body:
            print(
                'body: %r resolved from %s; pass --legacy-phenotype for the old path'
                % (body, a.char_id if P.resolve_body_name(a.char_id) else a.char_asset)
            )
    spec = None
    if body:
        spec = P.registry_body(P.resolve_body_name(body))
    elif a.char_asset:
        spec = P.spec_for(char_asset=a.char_asset)
        print('body: LEGACY declared-build calibration — %s' % P.describe(spec))
    else:
        print(
            'body: none given — the anny DEFAULT body. This is almost certainly not '
            'the character; pass --body <registry name>.'
        )
    reps = []
    for d in dirs:
        if os.path.isdir(d) and os.path.exists(os.path.join(d, 'mesh.json')):
            r = fit_cell(d, body=spec)
            if a.out_name != 'anny_fit.json':
                import shutil

                shutil.move(os.path.join(d, 'anny_fit.json'), os.path.join(d, a.out_name))
            reps.append(r)
    ok = [r for r in reps if r.get('ok')]
    good = [r for r in ok if r.get('fit_ok')]
    full = [r['mean_err_px'] for r in good if r['fit_mode'] == 'full']
    upper = [r['mean_err_px'] for r in good if r['fit_mode'] == 'upper']
    print(
        'fitted %d/%d | PASSED GATE %d (full n=%d med %.1fpx | upper n=%d med %.1fpx)'
        ' | gated %d | declined %d'
        % (
            len(ok),
            len(reps),
            len(good),
            len(full),
            np.median(full) if full else -1,
            len(upper),
            np.median(upper) if upper else -1,
            len(ok) - len(good),
            len(reps) - len(ok),
        )
    )
    return 0


if __name__ == '__main__':
    sys.exit(main())
