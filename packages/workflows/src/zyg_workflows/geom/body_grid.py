# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""body_grid.py — the full-body mesh grid, drawn honestly, two ways (2026-08-04).

RUN:
    python3 -m zyg_workflows.geom.body_grid <char_id> [--char-asset char_abel] [--cells ...]

Two overlays per fitted cell, because they make DIFFERENT claims and the difference is
the point:

  overlay_body.png   THE ANATOMY LAYER. The fitted Anny body (13,718 verts, phenotype
                     locked to the declared build) projected as its real quad wireframe,
                     drawn WHERE THE FIT PUT IT — visibly inside the costume at the
                     breeches, because a body model models the body and Abel is wearing
                     17th-century clothes. Nothing is warped to flatter the silhouette;
                     this layer is for judging the FIT.

  overlay_wrap.png   THE SURFACE GRID. The same mesh after a 2D silhouette wrap: the
                     projected boundary is pulled onto the character's actual outline
                     (the region map's person silhouette — clothes, hair and all) and the
                     interior follows by Laplacian diffusion OVER THE MESH TOPOLOGY, so
                     vertex ids keep their meaning — vertex N is still "left knee, outer
                     side", it has just moved with the trousers. This is the grid that
                     hugs the drawn character, and it says so by construction: it is the
                     anatomy grid CONFORMED to the clothed outline, not a surface
                     reconstruction.

HOW THE WRAP WORKS, and its guard-rails:
  * correspondence  mesh-silhouette vertices (within 1.5px of the projected mesh's own
                    outline) are pulled to the NEAREST point of the person-mask boundary
                    (distance transform with per-pixel labels — exact nearest, no search)
  * interior        the displacement field diffuses across mesh adjacency (Jacobi over
                    the vertex graph), constrained verts pinned — smooth, topology-aware
  * the head        excluded from constraints. The person outline up there is HAIR; a
                    wrap that ballooned the skull to the hairline would fabricate a big
                    head, and the face already has a true 478-vertex mesh from the
                    detector. Head verts ride along on diffusion only.
  * eligibility     wrap only runs when knees and ankles are confidently detected — on a
                    portrait crop the mesh's legs project outside the frame, and pulling
                    them to the image border would invent geometry where there is none.
"""

import json
import os

import numpy as np

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None

GRID_COLOR_BODY = (255, 210, 90)  # cyan-ish: the anatomy layer
GRID_COLOR_WRAP = (250, 120, 250)  # magenta: the wrapped surface grid
ALPHA = 0.55


def _edges_from_quads(faces):
    e = set()
    for q in faces:
        n = len(q)
        for i in range(n):
            a, b = int(q[i]), int(q[(i + 1) % n])
            e.add((a, b) if a < b else (b, a))
    return np.array(sorted(e), np.int32)


def _project(char_asset, fit):
    """Posed, phenotype-locked vertices projected to image space.

    Returns (v2d, faces, arm_side): arm_side is +1/-1 for vertices on the model's
    left/right ARM (identified in REST space, where arms are unambiguous — vertex
    indices are pose-independent, so the mask survives any pose), 0 elsewhere.
    """
    import torch
    from anny.keypoints import KeypointsRegressor
    from .anny_fit import _rotmat
    from . import phenotype as P

    # THE OVERLAY MUST DRAW THE BODY THE FIT USED, not a body re-derived here. Before
    # 2026-09-02 this recalculated a height-only calibration from char_asset and drew
    # that, so an overlay could disagree with the fit that produced its pose — and for
    # the 35 abel cells fitted with no phenotype at all it drew a body the fit had never
    # seen. anny_fit now records the full body in the report; that record is the source.
    rec = fit.get('body') or {}
    spec = None
    if rec.get('source') == 'registry' and rec.get('name'):
        spec = P.registry_body(rec['name'], log=lambda *_: None)
        if rec.get('cage_vert_sha256') and spec.get('cage_vert_sha256_rebuilt') != rec['cage_vert_sha256']:
            raise ValueError(
                'this fit was made against cage %s but %r now rebuilds to %s — the '
                'overlay would draw a different body than the fit did'
                % (rec['cage_vert_sha256'][:16], rec['name'], (spec.get('cage_vert_sha256_rebuilt') or '')[:16])
            )
    elif fit.get('phenotype'):
        spec = P.legacy_spec(fit['phenotype'], why='recorded in the fit report')
    elif char_asset:
        spec = P.spec_for(char_asset=char_asset, log=lambda *_: None)
    if spec is None:
        spec = P.legacy_spec({}, why='the fit recorded no body (pre-2026-09-02 report)')
    m = P.body_model(spec)
    S44 = P.bone_scale_matrix(spec, m)
    pose = torch.tensor(fit['pose_aa'], dtype=torch.float32)
    with torch.no_grad():
        out = m(**P.forward_kwargs(spec, pose, model=m, scale44=S44))
        v = out['vertices'][0].to(torch.float32)
        rest = out['rest_vertices'][0].to(torch.float32).numpy()
        kr = KeypointsRegressor(m, labels=['left_shoulder', 'right_shoulder']).double()
        sh = kr({'rest_vertices': out['rest_vertices'], 'vertices': out['rest_vertices']})[0].numpy()
    shoulder_x = float(np.abs(sh[:, 0]).mean())
    arm_side = np.zeros(len(rest), np.int8)
    # 0.95, not 1.12: cutting outboard of the shoulder left open deltoid rings that
    # rendered as wing-like flaps beside the head. Cutting AT the shoulder line takes the
    # whole deltoid with the arm and the torso boundary closes cleanly.
    arm_side[rest[:, 0] > shoulder_x * 0.95] = 1  # model left arm
    arm_side[rest[:, 0] < -shoulder_x * 0.95] = -1  # model right arm

    R = _rotmat(torch.tensor(fit['global_aa'], dtype=torch.float32))
    p = (v @ R.T).numpy()
    cam = fit['camera']
    near_invalid = None
    if fit.get('camera_model') == 'pinhole':
        f, tz, cx, cy = cam
        zc = p[:, 1] + tz
        # vertices at/behind the near plane project to infinity; clamping them merely
        # smears them into wide 'curtains' at the frame edges (seen on close portraits,
        # where the chest sits near the camera). They are invalid, not drawable.
        near_invalid = zc <= 0.27
        z = np.clip(zc, 0.25, None)
        x = f * p[:, 0] / z + cx
        y = f * (-p[:, 2]) / z + cy
    else:  # legacy orthographic fits
        x = p[:, 0] * cam[0] + cam[1]
        y = -p[:, 2] * cam[0] + cam[2]
    faces = m.faces.numpy() if hasattr(m.faces, 'numpy') else np.asarray(m.faces)
    if near_invalid is not None and near_invalid.any():
        faces = faces[~near_invalid[faces].any(axis=1)]
    return np.stack([x, y], -1).astype(np.float32), faces, arm_side


def _nearest_boundary_lut(mask):
    """(dt_labels, lut) so that lut[labels[y,x]] = nearest boundary pixel (x,y)."""
    b = mask.astype(np.uint8) ^ cv2.erode(mask.astype(np.uint8), np.ones((3, 3), np.uint8))
    src = np.where(b > 0, 0, 255).astype(np.uint8)
    _, labels = cv2.distanceTransformWithLabels(src, cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL)
    ys, xs = np.nonzero(src == 0)
    lut = np.zeros((labels.max() + 1, 2), np.float32)
    lut[labels[ys, xs]] = np.stack([xs, ys], -1)
    return labels, lut


def silhouette_wrap(v2d, faces, person, chin_y, region_map=None, body_lm=None, iters=160):
    """Pull the projected mesh onto the person outline; diffuse over topology.

    REGION-AWARE CORRESPONDENCE — the fix for the crotch webbing. The first version
    matched every silhouette vertex to the globally nearest outline pixel, and between
    the thighs "nearest" is frequently the OTHER leg: crotch vertices grabbed the far
    breech's boundary and the wrap webbed the legs together with crossing edges. The
    region map already knows which leg is which, so each vertex is first assigned a body
    region (sampled from regions.png, or by nearest skeleton bone when it projects into
    a gap) and may only target the outer boundary of ITS OWN region. A left-thigh vertex
    can no longer be attracted by the right breech, however near it is.
    """
    H, W = person.shape
    sil = np.zeros((H, W), np.uint8)
    pts = v2d.astype(np.int32)
    for q in faces:
        cv2.fillConvexPoly(sil, pts[q], 255)
    band = cv2.dilate(sil, np.ones((3, 3), np.uint8)) ^ cv2.erode(sil, np.ones((5, 5), np.uint8))

    xi = np.clip(pts[:, 0], 0, W - 1)
    yi = np.clip(pts[:, 1], 0, H - 1)
    on_sil = band[yi, xi] > 0
    below_chin = v2d[:, 1] > chin_y
    outside = person[yi, xi] == 0
    constrained = (on_sil | outside) & below_chin

    d = np.zeros_like(v2d)
    if region_map is None:
        labels, lut = _nearest_boundary_lut(person)
        tgt = lut[labels[yi, xi]]
        d[constrained] = tgt[constrained] - v2d[constrained]
    else:
        from . import regions as R
        from . import keypoints as K

        # vertex -> region: sample the map; gaps (crotch, underarm) resolve by nearest
        # bone, exactly the assignment rule the region builder itself uses
        vreg = region_map[yi, xi].astype(np.int32)
        need = (vreg == 0) & constrained
        if need.any() and body_lm is not None:
            pts2 = {n: body_lm[K.P[n], :2] for n in K.POSE_NAMES}
            pts2['mid_shoulder'] = (pts2['left_shoulder'] + pts2['right_shoulder']) / 2
            pts2['mid_hip'] = (pts2['left_hip'] + pts2['right_hip']) / 2
            P2 = v2d[need]
            best_d = np.full(len(P2), np.inf, np.float32)
            best_id = np.zeros(len(P2), np.int32)
            for region, bones in R._BONES:
                rid = R.REGION_IDX[region]
                for a, bn, wsc in bones:
                    A_, B_ = pts2[a], pts2[bn]
                    AB = B_ - A_
                    L2 = float(AB @ AB) or 1e-6
                    t = np.clip(((P2 - A_) @ AB) / L2, 0.0, 1.0)
                    dist = np.linalg.norm(P2 - (A_ + t[:, None] * AB), axis=1) / wsc
                    sel = dist < best_d
                    best_d[sel] = dist[sel]
                    best_id[sel] = rid
            vreg[need] = best_id
        # per-region outer boundary (region pixels adjacent to BACKGROUND only —
        # internal region-to-region borders must not attract)
        bg = (person == 0).astype(np.uint8)
        near_bg = cv2.dilate(bg, np.ones((3, 3), np.uint8)) > 0
        for rid in np.unique(vreg[constrained]):
            if rid <= 0:
                continue
            sel = constrained & (vreg == rid)
            rb = ((region_map == rid) & near_bg).astype(np.uint8)
            if rb.sum() < 8:
                continue
            src = np.where(rb > 0, 0, 255).astype(np.uint8)
            _, labels = cv2.distanceTransformWithLabels(src, cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL)
            ys2, xs2 = np.nonzero(src == 0)
            lut = np.zeros((labels.max() + 1, 2), np.float32)
            lut[labels[ys2, xs2]] = np.stack([xs2, ys2], -1)
            tgt = lut[labels[yi[sel], xi[sel]]]
            d[sel] = tgt - v2d[sel]

    # DISPLACEMENT CAP. A vertex that must travel further than ~half a shoulder-width is
    # no longer following the body's surface — it is chasing wardrobe (measured: the
    # flared coat panel ballooned Abel's wrapped thigh). Oversized pulls are scaled back
    # rather than dropped, so the direction survives but the balloon cannot.
    if body_lm is not None:
        from . import keypoints as K2

        sw = float(np.linalg.norm(body_lm[K2.P['left_shoulder'], :2] - body_lm[K2.P['right_shoulder'], :2])) or 60.0
        cap = 0.45 * sw
        mag = np.linalg.norm(d, axis=1)
        over = mag > cap
        if over.any():
            d[over] *= (cap / mag[over])[:, None]

    # Laplacian diffusion of d over vertex adjacency, constrained verts pinned
    from scipy import sparse

    edges = _edges_from_quads(faces)
    n = len(v2d)
    A = sparse.coo_matrix(
        (
            np.ones(len(edges) * 2),
            (np.concatenate([edges[:, 0], edges[:, 1]]), np.concatenate([edges[:, 1], edges[:, 0]])),
        ),
        shape=(n, n),
    ).tocsr()
    deg = np.asarray(A.sum(1)).ravel().clip(min=1)
    free = ~constrained
    for _ in range(iters):
        avg = (A @ d) / deg[:, None]
        d[free] = avg[free]
    p = v2d + d

    # BOUNDARY RELAXATION. Nearest-point matching compresses many vertices into concave
    # notches (the crotch V collected a bunched fan of boundary verts). A few smoothing
    # passes over the CONSTRAINED verts' final positions spread them back out along the
    # outline; the interior then re-diffuses briefly so the grid stays coherent.
    for _ in range(12):
        avg = (A @ p) / deg[:, None]
        p[constrained] = 0.6 * p[constrained] + 0.4 * avg[constrained]
    d2 = p - v2d
    for _ in range(30):
        avg = (A @ d2) / deg[:, None]
        d2[free] = avg[free]
    return v2d + d2


def _draw_grid(img, v2d, faces, colour):
    layer = img.copy()
    e = _edges_from_quads(faces)
    p = v2d.astype(np.int32)
    H, W = img.shape[:2]
    ok = (p[:, 0] > -W) & (p[:, 0] < 2 * W) & (p[:, 1] > -H) & (p[:, 1] < 2 * H)
    for a, b in e:
        if ok[a] and ok[b]:
            cv2.line(layer, tuple(p[a]), tuple(p[b]), colour, 1, cv2.LINE_AA)
    return cv2.addWeighted(layer, ALPHA, img, 1 - ALPHA, 0)


def build_cell(cell_dir, char_asset=''):
    from . import keypoints as K

    fitp = os.path.join(cell_dir, 'anny_fit.json')
    if not os.path.exists(fitp):
        return None
    fit = json.load(open(fitp))
    if 'pose_aa' not in fit:
        return None
    out = {'cell': os.path.basename(cell_dir)}

    # THE HONESTY GATE. A failed fit rendered confidently is worse than no render — the
    # 276.8px cell_31 fit drew a torso the size of the frame and LOOKED authoritative.
    # Gated cells get their stale overlays REMOVED, not merely skipped: an old wrong
    # image on disk is indistinguishable from a current right one.
    if not fit.get('fit_ok', True):
        removed = []
        for f in ('overlay_body.png', 'overlay_wrap.png', 'wrap_v2d.npy'):
            p = os.path.join(cell_dir, f)
            if os.path.exists(p):
                os.remove(p)
                removed.append(f)
        out.update(
            overlay_body=False,
            overlay_wrap=False,
            gated='fit err %.3f torso > %.2f%s'
            % (
                fit.get('err_over_torso', 9),
                fit.get('gate_threshold', 0.08),
                ('; removed ' + ','.join(removed)) if removed else '',
            ),
        )
        return out

    mesh = json.load(open(os.path.join(cell_dir, 'mesh.json')))
    img = cv2.imread(mesh['image'])
    rm = cv2.imread(os.path.join(cell_dir, 'regions.png'), cv2.IMREAD_GRAYSCALE)
    if img is None or rm is None:
        return None  # source gone (quarantined) — nothing to draw on
    person = (rm > 0).astype(np.uint8)

    v2d, faces, arm_side = _project(char_asset, fit)

    # UPPER-MODE FITS DRAW ONLY WHAT THE EVIDENCE SUPPORTS — in two dimensions.
    # Vertically: nothing below draw_limit_y (below the lowest real keypoint the body is
    # imagination). And PER ARM: with only face+shoulder evidence an arm's pose is
    # under-determined — measured on cell_00, three fitter variants in a row folded a
    # giant arm across the sky, each 2D-consistent and each wrong. No prior weight fixes
    # under-determination; not drawing it does. An arm is rendered only when ITS side has
    # a real elbow or wrist detection.
    draw_faces = faces
    if fit.get('fit_mode') == 'upper':
        keep = np.ones(len(faces), bool)
        if fit.get('draw_limit_y'):
            lim = float(fit['draw_limit_y'])
            keep &= v2d[faces, 1].max(axis=1) < lim
        with open(os.path.join(cell_dir, 'mesh.json')) as fh:
            mj = json.load(fh)
        bb = np.asarray(mj['body_landmarks'], np.float32)
        Wm, Hm = mj['size']
        for side, sign in (('left', 1), ('right', -1)):
            # same in-frame guard as the fitter: an off-frame landmark is not evidence
            has_arm = any(
                bb[K.P['%s_%s' % (side, j)], 2] >= 0.5
                and 0 <= bb[K.P['%s_%s' % (side, j)], 0] < Wm
                and 0 <= bb[K.P['%s_%s' % (side, j)], 1] < Hm
                for j in ('elbow', 'wrist')
            )
            if not has_arm:
                keep &= ~(arm_side[faces] == sign).any(axis=1)
        draw_faces = faces[keep]
        out['faces_drawn'] = '%d/%d (upper: evidence-limited)' % (len(draw_faces), len(faces))

    # THE GRID DESCRIBES THE CHARACTER. Faces that project entirely onto background —
    # the flaring torso-rim 'curtains' seen on close portraits — assert geometry where
    # the image shows none. A face must touch the (generously dilated) person mask to be
    # drawn; the 60px margin keeps honest silhouette overhang, kills the curtains.
    persond = cv2.dilate(person, np.ones((61, 61), np.uint8))
    Hm2, Wm2 = persond.shape
    fx = np.clip(v2d[draw_faces, 0].astype(int), 0, Wm2 - 1)
    fy = np.clip(v2d[draw_faces, 1].astype(int), 0, Hm2 - 1)
    on_person = persond[fy, fx].any(axis=1)
    draw_faces = draw_faces[on_person]

    body = _draw_grid(img, v2d, draw_faces, GRID_COLOR_BODY)
    cv2.imwrite(os.path.join(cell_dir, 'overlay_body.png'), body)
    out['overlay_body'] = True

    # wrap eligibility: full fit only, legs actually in frame and detected
    b = np.asarray(mesh['body_landmarks'], np.float32)
    legs_ok = fit.get('fit_mode', 'full') == 'full' and all(
        b[K.P[n], 2] >= 0.5 for n in ('left_knee', 'right_knee', 'left_ankle', 'right_ankle')
    )
    if legs_ok:
        if mesh.get('face') and mesh.get('face_landmarks'):
            chin_y = float(np.asarray(mesh['face_landmarks'])[152][1])
        else:
            sh = (b[K.P['left_shoulder'], 1] + b[K.P['right_shoulder'], 1]) / 2
            chin_y = float(sh - 0.35 * abs(b[K.P['left_shoulder'], 0] - b[K.P['right_shoulder'], 0]))
        wrapped = silhouette_wrap(v2d, faces, person, chin_y, region_map=rm, body_lm=b)
        wrap_img = _draw_grid(img, wrapped, faces, GRID_COLOR_WRAP)
        cv2.imwrite(os.path.join(cell_dir, 'overlay_wrap.png'), wrap_img)
        out['overlay_wrap'] = True
        np.save(os.path.join(cell_dir, 'wrap_v2d.npy'), wrapped)
    else:
        out['overlay_wrap'] = False
        out['wrap_skipped'] = 'legs not confidently in frame — wrap would invent geometry'
    return out


if __name__ == '__main__':  # the CLI lives in body_grid_cli
    from zyg_workflows.geom.body_grid_cli import main as _cli_main

    raise SystemExit(_cli_main())
