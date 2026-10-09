# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: F401  this module inherits head_fit.py's original top import block; the
# sibling modules import argparse/time/json/os from here, so every name must stay bound.

from __future__ import annotations

import argparse
import json
import os
import time

from zyg_workflows import paths

# head_fit.py became this package. _HERE is the geom/ directory the single file sat in and
# _CREWS the zyg_workflows package directory it derived every path from; both come from
# zyg_workflows.paths now, so no module has to claim the deleted file's __file__.
_HERE = str(paths.PKG_DIR / 'geom')
_CREWS = str(paths.PKG_DIR)
ICT_DIR = str(paths.DATA_DIR / 'assets' / 'ict_facekit')
CORR_PATH = os.path.join(ICT_DIR, 'mp468_to_ibug68.json')
MP_CANON = os.path.join(ICT_DIR, 'canonical_face_model.obj')
FACEMESH = os.path.join(ICT_DIR, 'mediapipe_facemesh_sets.json')
CHAR_MESH = str(paths.PKG_DIR / 'output' / 'char_mesh')
OUT_ROOT = str(paths.PKG_DIR / 'output' / 'head_fit')

# iBUG-68 groups -> the FACEMESH set a landmark is allowed to match inside.
IBUG_GROUPS = [
    (range(0, 17), 'FACEMESH_FACE_OVAL'),
    (range(17, 22), 'RIGHT_EYEBROW'),  # iBUG right = subject right = -x
    (range(22, 27), 'LEFT_EYEBROW'),
    (range(27, 36), 'FACEMESH_NOSE'),
    (range(36, 42), 'RIGHT_EYE'),
    (range(42, 48), 'LEFT_EYE'),
    (range(48, 68), 'FACEMESH_LIPS'),
]
JAW = list(range(0, 17))
JAW_WEIGHT = 0.0  # MEASURED off, not assumed: GNM and ICT place their
# iBUG 0-16 anchors 35.5 mm rms / 84.8 mm max apart
# (build_correspondence, jaw_disagreement), so a
# MediaPipe FACE_OVAL target aimed at a GNM jaw anchor
# is a systematic bias, not evidence. Ablation at 0.25
# is run and reported rather than argued.
YAW_LIMIT = 1.05  # rad (~60 deg): past this the jawline map is fiction
MIN_LANDMARKS = 40
EXPR_LANDMARK_MIN_M = 2e-4  # a GNM expression component that moves no landmark
# by 0.2 mm is unidentifiable from landmarks: dropped
_CACHE: dict = {}

# ── correspondence ───────────────────────────────────────────────────────────


def _similarity(src, dst):
    """(scale, R [3,3], t [3]) least-squares similarity src -> dst (Umeyama)."""
    import numpy as np

    sc, dc = src.mean(0), dst.mean(0)
    s0, d0 = src - sc, dst - dc
    U, S, Vt = np.linalg.svd(s0.T @ d0 / len(src))
    d = np.sign(np.linalg.det(U @ Vt))
    D = np.diag([1.0, 1.0, d])
    R = (U @ D @ Vt).T
    scale = float(S @ np.diag(D).ravel() / max((s0**2).sum() / len(src), 1e-12))
    t = dc - scale * (R @ sc)
    return scale, R, t


def _frame_check(mp, ict, gnm_lm, log=print):
    """Assert the three frames share the X-right/Y-up/Z-forward layout, by
    measurement. A silent axis swap here would produce a plausible-looking fit
    against a mirrored face, which is the failure this check exists to stop."""

    out = {}
    for nm, v in (('mediapipe_canonical', mp), ('ict_neutral', ict)):
        span = v.max(0) - v.min(0)
        out[nm] = {
            'bbox_span': [round(float(x), 3) for x in span],
            'x_symmetric': bool(abs(v[:, 0].max() + v[:, 0].min()) < 0.05 * span[0]),
        }
    # chin below eyes, nose tip most forward — true in every one of the three
    for nm, L in (('ict_68', ict[_CACHE['ict_lm_idx']]), ('gnm_68', gnm_lm)):
        ok_up = bool(L[8, 1] < L[36, 1] and L[8, 1] < L[45, 1])
        ok_fwd = bool(L[30, 2] > L[8, 2] and L[30, 2] > L[36, 2])
        ok_side = bool(L[36, 0] < 0 < L[45, 0])
        out[nm] = {'chin_below_eyes': ok_up, 'nosetip_most_forward': ok_fwd, 'ibug36_on_negative_x': ok_side}
        if not (ok_up and ok_fwd and ok_side):
            raise RuntimeError(
                f'{nm} frame is not X-right/Y-up/Z-forward iBUG-68 ({out[nm]}) — correspondence would be mirrored'
            )
    log(f'[head_fit] frame check OK: {json.dumps(out)}')
    return out


def build_correspondence(log=print):
    """Derive MP468 -> iBUG68 and cache it with per-landmark residuals."""
    import numpy as np
    from zyg_workflows.geom import ict_face as I
    from zyg_workflows.geom import gnm_head as GH

    mp, _ = I._read_obj(MP_CANON)
    if mp.shape[0] != 468:
        raise RuntimeError(f'canonical_face_model.obj has {mp.shape[0]} verts, expected 468')
    sets = json.load(open(FACEMESH, encoding='utf-8'))['sets']
    m = I.model()
    ict = I.deform()
    _CACHE['ict_lm_idx'] = np.asarray(m['landmarks68'])
    ict_lm = ict[_CACHE['ict_lm_idx']]
    gnm_lm = GH.landmark_points(GH.vertices_for(GH.neutral_params()))
    frame = _frame_check(mp, ict, gnm_lm, log=log)

    # Does GNM's sparse-68 really use ICT's ordering? Procrustes says.
    # THE ORDERING TEST IS RUN WITHOUT THE JAWLINE, and the reason is itself a
    # finding: on the full 68 the two models sit 18.4 mm apart, but that number
    # is made almost entirely of iBUG 0-16 (jaw rms 35.5 mm, max 84.8 mm) —
    # GNM and ICT do not place their jawline anchors on the same anatomy at all.
    # Landmarks 17-67 agree to 3.7 mm against a shuffled null of ~44 mm, which
    # settles the ordering question; the jaw disagreement is reported separately
    # and is why JAW_WEIGHT defaults to zero.
    nojaw = list(range(17, 68))
    s_ig, R_ig, t_ig = _similarity(ict_lm[nojaw], gnm_lm[nojaw])
    resid_ig = np.linalg.norm((s_ig * (ict_lm[nojaw] @ R_ig.T) + t_ig) - gnm_lm[nojaw], axis=1) * 1000.0
    rng = np.random.default_rng(0)
    shuf = []
    for _k in range(20):
        perm = rng.permutation(len(nojaw))
        s2, R2, t2 = _similarity(ict_lm[nojaw][perm], gnm_lm[nojaw])
        d = np.linalg.norm((s2 * (ict_lm[nojaw][perm] @ R2.T) + t2) - gnm_lm[nojaw], axis=1)
        shuf.append(float(np.sqrt(((d * 1000.0) ** 2).mean())))
    # the jaw, measured on its own through the whole-face alignment
    s_all, R_all, t_all = _similarity(ict_lm, gnm_lm)
    resid_all = np.linalg.norm((s_all * (ict_lm @ R_all.T) + t_all) - gnm_lm, axis=1) * 1000.0
    jaw_rms = float(np.sqrt((resid_all[JAW] ** 2).mean()))
    ord_rms = float(np.sqrt((resid_ig**2).mean()))
    log(
        f'[head_fit] ICT-68 vs GNM-68 ordering (landmarks 17-67): Procrustes rms '
        f'{ord_rms:.2f} mm (NULL, 20 shuffles: {float(np.mean(shuf)):.2f} mm mean, '
        f'{float(np.min(shuf)):.2f} best)'
    )
    log(
        f'[head_fit] JAWLINE DISAGREEMENT: iBUG 0-16 sit {jaw_rms:.1f} mm rms '
        f'(max {float(resid_all[JAW].max()):.1f} mm) apart between the two models — '
        f'the two projects anchor "jawline" to different anatomy'
    )

    # side-resolved FACEMESH sets: named by MEASURED sign of x, never by label
    def side_sets(a, b):
        ia, ib = sets[a]['indices'], sets[b]['indices']
        return (ia, ib) if mp[ia][:, 0].mean() < mp[ib][:, 0].mean() else (ib, ia)

    r_eye, l_eye = side_sets('FACEMESH_RIGHT_EYE', 'FACEMESH_LEFT_EYE')
    r_brow, l_brow = side_sets('FACEMESH_RIGHT_EYEBROW', 'FACEMESH_LEFT_EYEBROW')
    group_idx = {'RIGHT_EYE': r_eye, 'LEFT_EYE': l_eye, 'RIGHT_EYEBROW': r_brow, 'LEFT_EYEBROW': l_brow}
    for k in ('FACEMESH_FACE_OVAL', 'FACEMESH_NOSE', 'FACEMESH_LIPS'):
        group_idx[k] = sets[k]['indices']

    # eight geometric anchors, all extrema inside a set — no recalled index
    lips = np.asarray(group_idx['FACEMESH_LIPS'])
    oval = np.asarray(group_idx['FACEMESH_FACE_OVAL'])
    nose_i = np.asarray(group_idx['FACEMESH_NOSE'])
    re, le = np.asarray(r_eye), np.asarray(l_eye)
    anchors = {
        30: int(nose_i[np.argmax(mp[nose_i][:, 2])]),  # nose tip
        8: int(oval[np.argmin(mp[oval][:, 1])]),  # chin
        36: int(re[np.argmin(mp[re][:, 0])]),  # R eye outer
        39: int(re[np.argmax(mp[re][:, 0])]),  # R eye inner
        42: int(le[np.argmin(mp[le][:, 0])]),  # L eye inner
        45: int(le[np.argmax(mp[le][:, 0])]),  # L eye outer
        48: int(lips[np.argmin(mp[lips][:, 0])]),  # mouth R corner
        54: int(lips[np.argmax(mp[lips][:, 0])]),  # mouth L corner
    }
    a_ibug = sorted(anchors)
    s, R, t = _similarity(mp[[anchors[i] for i in a_ibug]], ict_lm[a_ibug])
    mp_a = s * (mp @ R.T) + t  # MP in ICT frame (cm)
    log(f'[head_fit] anchors {anchors} -> similarity scale {s:.4f}')

    # greedy unique nearest-neighbour inside each landmark's own set
    mapping = [None] * 68
    resid = [None] * 68
    for rng_i, gname in IBUG_GROUPS:
        cand = list(group_idx[gname])
        pairs = []
        for i in rng_i:
            d = np.linalg.norm(mp_a[cand] - ict_lm[i], axis=1)
            for j, dd in enumerate(d):
                pairs.append((float(dd), int(i), int(cand[j])))
        pairs.sort()
        used_i, used_j = set(), set()
        for dd, i, j in pairs:
            if i in used_i or j in used_j:
                continue
            mapping[i] = j
            resid[i] = dd * 10.0  # cm -> mm
            used_i.add(i)
            used_j.add(j)
            if len(used_i) == len(list(rng_i)):
                break
    if any(v is None for v in mapping):
        miss = [i for i, v in enumerate(mapping) if v is None]
        raise RuntimeError(f'no MediaPipe vertex left for iBUG landmarks {miss}')
    if len(set(mapping)) != 68:
        raise RuntimeError('mapping is not injective')

    # refit the similarity on the FULL map and re-measure (the honest residual)
    s2, R2, t2 = _similarity(mp[mapping], ict_lm)
    mp_full = s2 * (mp @ R2.T) + t2
    resid_full = np.linalg.norm(mp_full[mapping] - ict_lm, axis=1) * 10.0
    grp_rms = {}
    for rng_i, gname in IBUG_GROUPS:
        r = resid_full[list(rng_i)]
        grp_rms[gname] = round(float(np.sqrt((r**2).mean())), 2)
    doc = {
        'derived': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'method': 'eight geometric anchors (extrema inside FACEMESH sets) -> Umeyama '
        'similarity -> greedy unique nearest neighbour inside each iBUG '
        "group's own FACEMESH set -> similarity refit on all 68",
        'sources': {
            'mediapipe_canonical': MP_CANON,
            'facemesh_sets': FACEMESH,
            'ibug68_reference': 'ICT FaceKit vertex_indices.json:idx_to_landmark_verts',
        },
        'frame_check': frame,
        'ibug_ordering_check': {
            'scored_on': 'iBUG 17-67 (jawline excluded, see jaw_disagreement)',
            'ict68_to_gnm68_procrustes_rms_mm': round(ord_rms, 3),
            'null_shuffled_order_rms_mm_mean': round(float(np.mean(shuf)), 3),
            'null_shuffled_order_rms_mm_best': round(float(np.min(shuf)), 3),
            'verdict': ('same ordering' if ord_rms < 0.25 * float(np.min(shuf)) else 'DISAGREE'),
        },
        'jaw_disagreement': {
            'ict68_vs_gnm68_jaw_rms_mm': round(jaw_rms, 2),
            'ict68_vs_gnm68_jaw_max_mm': round(float(resid_all[JAW].max()), 2),
            'full68_rms_mm': round(float(np.sqrt((resid_all**2).mean())), 2),
            'consequence': 'a MediaPipe FACE_OVAL point steered at a GNM jaw anchor '
            'carries a systematic error of this size, so JAW_WEIGHT '
            'defaults to 0.0 and the ablation at 0.25 is reported.',
        },
        'anchors': {str(k): v for k, v in anchors.items()},
        'mp468_to_ibug68': [int(x) for x in mapping],
        'residual_mm': [round(float(x), 2) for x in resid_full],
        'residual_rms_mm': round(float(np.sqrt((resid_full**2).mean())), 2),
        'group_rms_mm': grp_rms,
        'jaw_note': 'iBUG 0-16 are 2D silhouette points; both reference meshes pin '
        'them to fixed vertices, so this part of the map is the weakest. '
        f'fit_cell weights them {JAW_WEIGHT}.',
    }
    os.makedirs(ICT_DIR, exist_ok=True)
    with open(CORR_PATH, 'w', encoding='utf-8') as f:
        json.dump(doc, f, indent=1)
    log(f'[head_fit] correspondence -> {CORR_PATH}: rms {doc["residual_rms_mm"]} mm, by group {grp_rms}')
    return doc


def correspondence():
    if 'corr' not in _CACHE:
        if not os.path.isfile(CORR_PATH):
            raise FileNotFoundError(
                f'{CORR_PATH} missing — run: /usr/bin/python3.12 -m zyg_workflows.geom.head_fit corr'
            )
        _CACHE['corr'] = json.load(open(CORR_PATH, encoding='utf-8'))
    return _CACHE['corr']
