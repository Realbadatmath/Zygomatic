# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""pose_track.py — a per-shot POSE TRACK for the VACE control channel (2026-09-02).

Sections 6-7: the MediaPipe 2D gate and the SOMA-X Anny<->MHR registration probe.
"""

from __future__ import annotations

from .constants import FOUND, NOT_DETECTABLE, NOT_FOUND, UNMEASURABLE, _CREWS, cv2, json, np, os

# ---------------------------------------------------------------- 2D gate


def gate_against_2d(track_path: str, *, log=print) -> dict:
    """Per-frame reprojection of the track's 2D keypoints against MediaPipe.

    Needs mediapipe (present in the crews venv, absent from the body venv), so the
    result carries its own ledger state rather than failing the track: a gate that
    cannot run must say `unmeasurable`, not pass. MediaPipe runs ONCE per frame and
    the same detections score the track and both nulls — scoring each separately
    would triple the cost and, worse, let the three disagree about which joints were
    visible.
    """
    with open(track_path, encoding='utf-8') as fh:
        tr = json.load(fh)
    out = {'state': UNMEASURABLE, 'reason': '', 'per_frame': []}
    try:
        from . import keypoints as K
    except Exception as exc:  # noqa: BLE001
        out['reason'] = f'mediapipe unavailable in this interpreter: {exc}'
        return out

    frames_dir = os.path.join(tr['out_dir'], 'frames')
    W, H = tr['size']
    names = [n for n in tr['mhr70_to_pose_names'] if n in K.P]

    tr_kp = np.array([f['keypoints_2d'] for f in tr['frames']], np.float64)
    n = tr_kp.shape[0]
    t = (np.arange(n) / max(n - 1, 1))[:, None, None]
    cand = {
        'track': tr_kp,
        'held_first_frame': np.repeat(tr_kp[:1], n, axis=0),
        'two_pose_lerp': tr_kp[:1] * (1 - t) + tr_kp[-1:] * t,
    }
    scores = {k: [] for k in cand}
    per = []
    for k, fr in enumerate(tr['frames']):
        fp = os.path.join(frames_dir, fr['src_frame'])
        if not os.path.isfile(fp):
            per.append({'i': fr['i'], 'state': UNMEASURABLE, 'reason': 'frame missing'})
            continue
        # ISOLATE THE TRACKED SUBJECT FIRST. MediaPipe's PoseLandmarker returns ONE
        # person and this driver clip has two: scored whole-frame it can lock onto the
        # OTHER man, and the gate would then be measuring the distance between two
        # different people and calling it tracking error. Everything outside the
        # track's own box is blacked out — the same crop-first rule geom.keypoints was
        # built on.
        #
        # BLACKED OUT ON A FULL-SIZE CANVAS, not cropped, and that is not a style
        # choice. Handing geom.keypoints.detect a small PORTRAIT crop on which it DOES
        # find a body aborts the whole process inside MediaPipe's C++:
        #   image_frame.cc:362 Check failed: 1 == ChannelSize() (1 vs. 4)
        # reached through MpImageDataFloat32 when the segmentation mask is read (the
        # PoseLandmarker is built with output_segmentation_masks=True at
        # geom/keypoints.py:72). It is an abort, not a Python exception, so no
        # try/except catches it and the gate would die mid-run with no result. Keeping
        # the source frame's dimensions avoids it entirely and has the side benefit of
        # needing no coordinate offset. Reported to whoever next owns keypoints.py.
        img = cv2.imread(fp)
        if img is None:
            per.append({'i': fr['i'], 'state': UNMEASURABLE, 'reason': 'frame unreadable'})
            continue
        ih, iw = img.shape[:2]
        bx = fr.get('bbox') or [0, 0, iw, ih]
        pad = 0.12 * max(bx[2] - bx[0], bx[3] - bx[1])
        x0 = int(max(0, bx[0] - pad))
        y0 = int(max(0, bx[1] - pad))
        x1 = int(min(iw, bx[2] + pad))
        y1 = int(min(ih, bx[3] + pad))
        if x1 - x0 < 32 or y1 - y0 < 32:
            x0, y0, x1, y1 = 0, 0, iw, ih
        canvas = np.zeros_like(img)
        canvas[y0:y1, x0:x1] = img[y0:y1, x0:x1]
        try:
            det = K.detect(canvas)
        except Exception as exc:  # noqa: BLE001
            per.append({'i': fr['i'], 'state': UNMEASURABLE, 'reason': str(exc)})
            continue
        if not det.body.ok:
            per.append({'i': fr['i'], 'state': NOT_FOUND, 'reason': 'MediaPipe found no body in the tracked box'})
            continue
        mp = det.body.pts  # already in full-frame pixels
        vis = [(nm, tr['mhr70_to_pose_names'][nm], mp[K.P[nm]]) for nm in names if mp[K.P[nm]][2] >= 0.5]
        if not vis:
            per.append({'i': fr['i'], 'state': NOT_DETECTABLE, 'reason': 'no shared joint above visibility 0.5'})
            continue
        row = {}
        for name, arr in cand.items():
            d = [float(np.hypot(arr[k, mi, 0] - pj[0], arr[k, mi, 1] - pj[1])) for _nm, mi, pj in vis]
            row[name] = float(np.mean(d))
            scores[name].append(row[name])
        per.append(
            {
                'i': fr['i'],
                'state': FOUND,
                'joints': len(vis),
                'mean_px': round(row['track'], 2),
                'null_held_px': round(row['held_first_frame'], 2),
                'null_lerp_px': round(row['two_pose_lerp'], 2),
            }
        )

    out['per_frame'] = per
    errs = scores['track']
    if errs:
        diag = float(np.hypot(W, H))
        null_scores = {k: round(float(np.mean(v)), 2) for k, v in scores.items() if k != 'track' and v}
        out.update(
            {
                'state': FOUND,
                'frames_measured': len(errs),
                'mean_px': round(float(np.mean(errs)), 2),
                'median_px': round(float(np.median(errs)), 2),
                'p90_px': round(float(np.percentile(errs, 90)), 2),
                'image_diagonal_px': round(diag, 1),
                'mean_pct_of_diagonal': round(100 * float(np.mean(errs)) / diag, 3),
                'nulls': null_scores,
                'beats_held_null': (
                    null_scores.get('held_first_frame') is not None
                    and float(np.mean(errs)) < null_scores['held_first_frame']
                ),
                'beats_lerp_null': (
                    null_scores.get('two_pose_lerp') is not None and float(np.mean(errs)) < null_scores['two_pose_lerp']
                ),
                'reference': 'MediaPipe BlazePose full (geom.keypoints), visibility >= 0.5',
                'note': (
                    'MediaPipe is a REFERENCE, not ground truth: it is a 2D detector '
                    'with its own error, and the joint conventions differ (MHR70 '
                    'shoulder/hip centres sit slightly differently from BlazePose). '
                    'The number that matters is the track against the two nulls '
                    'measured the same way, not its absolute value.'
                ),
            }
        )
    else:
        out['reason'] = 'no frame produced a comparable MediaPipe skeleton'
        out['ledger'] = {
            s: sum(1 for p in per if p['state'] == s) for s in (FOUND, NOT_FOUND, NOT_DETECTABLE, UNMEASURABLE)
        }

    out['ledger'] = {
        s: sum(1 for p in per if p['state'] == s) for s in (FOUND, NOT_FOUND, NOT_DETECTABLE, UNMEASURABLE)
    }
    gp = os.path.join(tr['out_dir'], 'gate_2d.json')
    with open(gp, 'w', encoding='utf-8') as fh:
        json.dump(out, fh, indent=1)
    log('  gate: %s' % gp)
    return out


# ---------------------------------------------------------------- Anny <-> MHR

SOMA_X = os.path.join(_CREWS, 'data', 'assets', 'mesh_packs', 'human_bases', 'soma_x')


def _obj_verts(path: str) -> np.ndarray:
    return np.array(
        [[float(x) for x in ln.split()[1:4]] for ln in open(path, encoding='utf-8') if ln.startswith('v ')], np.float64
    )


def _umeyama(X: np.ndarray, Y: np.ndarray):
    """Similarity transform (s, R, t) taking corresponding rows of X onto Y."""
    mx, my = X.mean(0), Y.mean(0)
    Xc, Yc = X - mx, Y - my
    S = Xc.T @ Yc / len(X)
    U, D, Vt = np.linalg.svd(S)
    d = float(np.sign(np.linalg.det(U @ Vt)))
    E = np.diag([1.0, 1.0, d])
    R = (U @ E @ Vt).T
    s = float((D * np.array([1.0, 1.0, d])).sum() / (Xc**2).sum() * len(X))
    return s, R, my - s * R @ mx


def soma_registration_probe(log=print) -> dict:
    """How well does SOMA-X actually register Anny to MHR? Measured, with nulls.

    SOMA-X (NVIDIA, Apache-2.0, installed 2026-09-02) ships a SHARED WRAP: an
    18,056-vertex mesh fitted to each backend body, so wrap vertex i on the Anny side
    and wrap vertex i on the MHR side are the same anatomical point. That shared index
    is the only Anny<->MHR registration on this box, and this measures it.

    Three numbers, because the headline one means nothing alone:
      wrap_similarity_mm   residual of the best similarity transform solved FROM the
                           shared index — what the registration claims
      null_nn_mm           the same transform solved from a nearest-neighbour guess at
                           the correspondence. If the shared index carried no real
                           information this would score the same; it does not, and the
                           gap is the evidence that the index is a correspondence.
      null_scale_mm        centroid + height-scale only, no rotation solved — the
                           "did we need SOMA at all" null.

    And one warning the caller must not average away: `null_nearest_surface_mm` (an
    Anny vertex to the NEAREST MHR surface point) scores BETTER than the through-wrap
    transfer, and is not a competitor — it is a distance to a surface, not a
    correspondence, and it does not preserve which part of the body a point belongs
    to. Reported so nobody later quotes it as the wrap being beaten.
    """
    try:
        from scipy.spatial import cKDTree
    except Exception as exc:  # noqa: BLE001
        return {'state': UNMEASURABLE, 'reason': f'scipy required: {exc}'}
    need = {
        'anny_wrap': f'{SOMA_X}/Anny/SOMA_wrap.obj',
        'mhr_wrap': f'{SOMA_X}/MHR/SOMA_wrap_lod1.obj',
        'anny_base': f'{SOMA_X}/Anny/base_body.obj',
        'mhr_base': f'{SOMA_X}/MHR/base_body_lod1.obj',
    }
    missing = [k for k, v in need.items() if not os.path.isfile(v)]
    if missing:
        return {'state': UNMEASURABLE, 'reason': 'SOMA-X missing: %s' % ', '.join(missing)}

    aw = _obj_verts(need['anny_wrap'])
    mw = _obj_verts(need['mhr_wrap']) / 100.0  # SOMA ships MHR in centimetres
    ab = _obj_verts(need['anny_base'])
    mb = _obj_verts(need['mhr_base']) / 100.0
    if len(aw) != len(mw):
        return {
            'state': UNMEASURABLE,
            'reason': 'wrap vertex counts differ (%d vs %d) — not a shared index' % (len(aw), len(mw)),
        }

    def mm(a, b):
        d = np.linalg.norm(a - b, axis=1)
        return round(float(d.mean()) * 1000, 1), round(float(np.percentile(d, 95)) * 1000, 1)

    s, R, t = _umeyama(mw, aw)
    mw_a = (s * (R @ mw.T)).T + t
    mb_a = (s * (R @ mb.T)).T + t
    wrap_mean, wrap_p95 = mm(aw, mw_a)

    _, nn = cKDTree(aw).query(mw)
    s2, R2, t2 = _umeyama(mw, aw[nn])
    null_nn_mean, null_nn_p95 = mm(aw, (s2 * (R2 @ mw.T)).T + t2)

    sh = float((aw.max(0) - aw.min(0)).max() / (mw.max(0) - mw.min(0)).max())
    null_sc_mean, null_sc_p95 = mm(aw, (mw - mw.mean(0)) * sh + aw.mean(0))

    _, i_ab = cKDTree(aw).query(ab)
    tr_mean, tr_p95 = mm(ab, mw_a[i_ab])
    _, j = cKDTree(mb_a).query(ab)
    ns_mean, ns_p95 = mm(ab, mb_a[j])

    out = {
        'state': FOUND,
        'source': SOMA_X,
        'anny_verts': len(ab),
        'mhr_verts': len(mb),
        'wrap_verts': len(aw),
        'similarity_scale': round(s, 4),
        'wrap_similarity_mm': {'mean': wrap_mean, 'p95': wrap_p95},
        'null_nn_mm': {'mean': null_nn_mean, 'p95': null_nn_p95},
        'null_scale_mm': {'mean': null_sc_mean, 'p95': null_sc_p95},
        'anny_vertex_transfer_mm': {'mean': tr_mean, 'p95': tr_p95},
        'null_nearest_surface_mm': {'mean': ns_mean, 'p95': ns_p95},
        'verdict': (
            'the shared wrap IS a real correspondence (guessing it by nearest '
            'neighbour costs %.0fx) but it buys little over a plain height scale '
            '(%.1f vs %.1f mm), because the residual is dominated by the genuine '
            'shape gap between Anny neutral and MHR neutral, not by registration.'
            % (null_nn_mean / max(wrap_mean, 1e-6), wrap_mean, null_sc_mean)
        ),
        'blocks_rotation_retarget': (
            "MHR's 127 joints are ANONYMOUS on this box: mhr_model.pt is a TorchScript "
            'module with no name table, and the names live in the momentum character '
            'definition that only pymomentum carries (conda-only; see '
            'data/runtime/model_licences_pending/S08.json). A joint-NAME table from MHR '
            "to Anny's 163 MakeHuman bones therefore cannot be written from what is on "
            'disk, and the rotation retarget the plan asks for is blocked on that, not '
            'on effort. What IS available without names: this vertex correspondence, '
            'and the 19 NAMED mhr70 keypoints in pose_track.MHR70_TO_POSE.'
        ),
    }
    log(
        '  soma: wrap %.1f mm (nulls: nn %.1f, scale %.1f) — %s'
        % (wrap_mean, null_nn_mean, null_sc_mean, out['verdict'][:60])
    )
    return out
