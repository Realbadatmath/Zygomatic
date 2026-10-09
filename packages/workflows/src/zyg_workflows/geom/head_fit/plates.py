# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from zyg_workflows.geom.head_fit.cell_fit import landmark_weights
from zyg_workflows.geom.head_fit.corr_map import OUT_ROOT, _CACHE, _CREWS, correspondence, json, os, paths, time

# ═══════════════════════════════════════════════════════════════════════════
# EXPRESSION PLATES — ICT driven by MediaPipe blendshapes, rendered as depth
# and normal control plates in the SOURCE FRAME so S01/S08 can composite them.
#
# Why ICT and not GNM here: GNM's 383 expression components are unnamed
# per-region PCA (`left_eye_region_000` ...), so driving them from a video needs
# a fitter nobody has published. ICT's 53 targets carry the ARKit names
# MediaPipe already emits, so the driver signal IS the blendshape weight and no
# expression fit happens at all — only the rigid pose is solved.
#
# MediaPipe runs in the SERVER VENV (mediapipe 0.10.35 is installed there and
# deliberately not on 3.12, per the gnm_head "one leaf at a time" rule), so the
# driver pass is a subprocess and its output is a JSON file. Everything after
# that is numpy on 3.12.
# ═══════════════════════════════════════════════════════════════════════════

#: The server venv's interpreter — deliberately NOT ``sys.executable``: mediapipe is
#: installed there and not on 3.12 (see the note above).
VENV_PY = paths.ZYG_SERVER_PYTHON
PLATE_ROOT = os.path.join(OUT_ROOT, 'plates')

_DRIVER_SCRIPT = r"""
import sys, json, cv2, numpy as np
sys.path.insert(0, CREWS)
from zyg_workflows.geom import keypoints as K
video, out, stride, maxf = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
cap = cv2.VideoCapture(video)
frames, i = [], -1
while len(frames) < maxf:
    ok, bgr = cap.read()
    if not ok:
        break
    i += 1
    if i % stride:
        continue
    d = K.detect(bgr)
    h, w = bgr.shape[:2]
    if d.face.ok:
        frames.append({'frame': i, 'ok': True, 'size': [w, h],
                       'via': d.face.via,
                       'yaw': d.face.extra.get('yaw'),
                       'blendshapes': d.blendshapes,
                       'landmarks': [[round(float(x), 2) for x in p]
                                     for p in d.face.pts]})
    else:
        frames.append({'frame': i, 'ok': False, 'size': [w, h],
                       'reason': 'no face'})
json.dump({'video': video, 'stride': stride, 'frames': frames}, open(out, 'w'))
print('driver frames %d, face ok %d' % (len(frames), sum(1 for f in frames if f['ok'])))
"""


def extract_driver(video, out_json, stride=2, max_frames=40, log=print):
    """Run the MediaPipe cascade over a clip in the server venv and cache the
    per-frame 478 landmarks + 52 blendshape scores."""
    import subprocess

    os.makedirs(os.path.dirname(out_json) or '.', exist_ok=True)
    script = f'CREWS = {_CREWS!r}\n' + _DRIVER_SCRIPT
    r = subprocess.run(
        [VENV_PY, '-c', script, video, out_json, str(stride), str(max_frames)],
        capture_output=True,
        text=True,
        timeout=1800,
    )
    if r.returncode != 0:
        raise RuntimeError(f'driver pass failed rc={r.returncode}: {(r.stderr or r.stdout)[-500:]}')
    log(f'[head_fit] driver: {r.stdout.strip().splitlines()[-1]} -> {out_json}')
    return json.load(open(out_json, encoding='utf-8'))


def _ict_face_region():
    """(face_vertex_mask [26719] bool, face_triangles [F,3]) — ICT's own
    `idx_to_fitting_verts` (7801 verts, z from -1.8 to 13.1 cm) is the face
    proper: it excludes the back of the skull, which spans to z = -9.2. A plate
    that carried the whole head would put the occiput in the depth ramp and
    ruin the normalisation over the part anyone is conditioning on."""
    import numpy as np
    from zyg_workflows.geom import ict_face as I

    if 'ict_face_region' in _CACHE:
        return _CACHE['ict_face_region']
    with open(os.path.join(I.FACEX, 'vertex_indices.json'), encoding='utf-8') as f:
        vi = json.load(f)
    mask = np.zeros(I.N_VERTS, dtype=bool)
    mask[np.asarray(vi['idx_to_fitting_verts'], dtype=int)] = True
    tris = I.model()['faces']
    tris = tris[mask[tris].all(axis=1)]
    _CACHE['ict_face_region'] = (mask, tris)
    return mask, tris


def _pose_ict(target68, W, H, verts, lm_idx, yaw0=None, iters=600):
    """Solve rotation + depth + principal point that puts the ICT head's own 68
    landmarks on the detected ones. Identity and expression are FIXED (the
    expression came from the blendshapes; nothing about the face is invented
    here), so this is a 6-dof rigid+depth pose and nothing more.

    Returns (cam dict, landmark rms px)."""
    import numpy as np
    import torch
    import roma

    lm = torch.from_numpy((verts[lm_idx] / 100.0).astype('float32'))  # cm -> m
    T = torch.from_numpy(np.ascontiguousarray(target68.astype('float32')))
    F_PX = 1.35 * max(W, H)
    io_m = float(np.linalg.norm(lm[36].numpy() - lm[45].numpy()))
    io_px = float(np.linalg.norm(target68[36] - target68[45])) or 40.0
    tz0 = max(0.15, F_PX * io_m / io_px)
    w = torch.from_numpy(landmark_weights()).unsqueeze(1)
    best = None
    for seed in [0.0] if yaw0 is None else [0.0, float(yaw0), float(yaw0) * 1.6]:
        rv = torch.tensor([0.0, float(seed), 0.0], requires_grad=True)
        log_tz = torch.zeros(1, requires_grad=True)
        R0 = roma.rotvec_to_rotmat(rv.detach()).numpy()
        p0 = lm.numpy() @ R0.T
        zc0 = np.maximum(tz0 - p0[:, 2], 0.05)
        cx0 = float(target68[:, 0].mean() - (F_PX * p0[:, 0] / zc0).mean())
        cy0 = float(target68[:, 1].mean() - (F_PX * (-p0[:, 1]) / zc0).mean())
        dc = torch.zeros(2, requires_grad=True)
        opt = torch.optim.Adam([rv, log_tz, dc], lr=0.02)
        for _ in range(iters):
            opt.zero_grad()
            p = lm @ roma.rotvec_to_rotmat(rv).T
            zc = (tz0 * torch.exp(log_tz[0]) - p[:, 2]).clamp(min=0.05)
            uv = torch.stack(
                [F_PX * p[:, 0] / zc + cx0 + dc[0] * F_PX, F_PX * (-p[:, 1]) / zc + cy0 + dc[1] * F_PX], -1
            )
            ((w * (uv - T) ** 2).sum()).backward()
            opt.step()
        with torch.no_grad():
            p = lm @ roma.rotvec_to_rotmat(rv).T
            zc = (tz0 * torch.exp(log_tz[0]) - p[:, 2]).clamp(min=0.05)
            uv = torch.stack(
                [F_PX * p[:, 0] / zc + cx0 + dc[0] * F_PX, F_PX * (-p[:, 1]) / zc + cy0 + dc[1] * F_PX], -1
            )
            err = torch.linalg.norm(uv - T, dim=1)
            cam = {
                'f': F_PX,
                'rotvec': [float(x) for x in rv],
                'tz': float(tz0 * torch.exp(log_tz[0])),
                'cx': float(cx0 + dc[0] * F_PX),
                'cy': float(cy0 + dc[1] * F_PX),
                'rms_px': float((err**2).mean().sqrt()),
                'nojaw_rms_px': float((err[17:] ** 2).mean().sqrt()),
            }
        if best is None or cam['nojaw_rms_px'] < best['nojaw_rms_px']:
            best = cam
    return best, best['rms_px']


def _raster(verts_m, tris, cam, W, H, density=16.0, max_samples=6_000_000, seed=0):
    """Depth + camera-space normals by a dense back-face-culled point splat.

    NOT a scanline rasteriser, and said so plainly: triangles are sampled at
    barycentric points, the samples are projected, back-facing ones are dropped,
    and a z-buffer is taken with np.minimum.at. It is ~200 lines lighter than a
    Blender round trip and needs no GPU, which matters because S01/S06/S08 are
    using it.

    SAMPLING IS PROPORTIONAL TO PROJECTED AREA, and that is not a refinement —
    the first version drew a fixed 4 samples per triangle and the plates came
    back with 12.6% salt-and-pepper holes concentrated exactly where ICT's
    topology is coarse (scalp, cheek, neck) while the dense lip and eye regions
    were oversampled. Each triangle now gets ceil(area_px * density) samples, so
    coverage is uniform in IMAGE space whatever the mesh does. `density` is
    samples per projected px^2; 16 leaves ~4 sub-pixel samples per pixel edge.

    Returns (depth [H,W] float32 metres with NaN outside, normal [H,W,3]
    camera-space unit vectors, mask [H,W] bool, stats dict). `stats` carries
    BOTH coverage numbers: `bbox_fill` (how much of the bounding box the head
    occupies — a face is not a rectangle, so this is never 1.0 and is not a
    defect) and `interior_holes`, the fraction a 5x5 morphological close fills
    in, which IS the rasteriser's own failure and is what to watch.
    """
    import numpy as np
    import roma
    import torch

    R = roma.rotvec_to_rotmat(torch.tensor(cam['rotvec'], dtype=torch.float32)).numpy()
    v = verts_m @ R.T  # world -> camera-aligned
    a, b, c = v[tris[:, 0]], v[tris[:, 1]], v[tris[:, 2]]
    fn = np.cross(b - a, c - a)
    ln = np.linalg.norm(fn, axis=1, keepdims=True)
    fn = fn / np.maximum(ln, 1e-12)
    # camera looks along -Z in this frame (see the projection): a triangle is
    # visible when its normal has a positive Z component.
    front = fn[:, 2] > 0
    tris, a, b, c, fn = tris[front], a[front], b[front], c[front], fn[front]
    # smooth per-vertex normals, so the plate reads as a surface not a facet field
    vn = np.zeros_like(v)
    for k in range(3):
        np.add.at(vn, tris[:, k], fn * ln[front])
    vn /= np.maximum(np.linalg.norm(vn, axis=1, keepdims=True), 1e-12)
    na, nb, nc = vn[tris[:, 0]], vn[tris[:, 1]], vn[tris[:, 2]]

    # projected area per triangle, at each triangle's own depth
    def uv_of(q):
        z = np.maximum(cam['tz'] - q[:, 2], 0.05)
        return np.stack([cam['f'] * q[:, 0] / z + cam['cx'], cam['f'] * (-q[:, 1]) / z + cam['cy']], 1)

    ua, ub, uc = uv_of(a), uv_of(b), uv_of(c)
    area_px = 0.5 * np.abs(
        (ub[:, 0] - ua[:, 0]) * (uc[:, 1] - ua[:, 1]) - (uc[:, 0] - ua[:, 0]) * (ub[:, 1] - ua[:, 1])
    )
    counts = np.maximum(1, np.ceil(area_px * float(density))).astype(np.int64)
    total = int(counts.sum())
    if total > max_samples:  # keep memory bounded, honestly
        counts = np.maximum(1, (counts * (max_samples / total)).astype(np.int64))
        total = int(counts.sum())
    tri_of = np.repeat(np.arange(len(tris)), counts)

    rng = np.random.default_rng(seed)
    u = rng.random((total, 1), dtype=np.float32)
    w2 = rng.random((total, 1), dtype=np.float32)
    flip = (u + w2) > 1.0
    u = np.where(flip, 1.0 - u, u)
    w2 = np.where(flip, 1.0 - w2, w2)
    b0 = 1.0 - u - w2
    P = b0 * a[tri_of] + u * b[tri_of] + w2 * c[tri_of]
    N = b0 * na[tri_of] + u * nb[tri_of] + w2 * nc[tri_of]
    N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)

    zc = cam['tz'] - P[:, 2]
    ok = zc > 0.05
    P, N, zc = P[ok], N[ok], zc[ok]
    x = np.round(cam['f'] * P[:, 0] / zc + cam['cx']).astype(np.int64)
    y = np.round(cam['f'] * (-P[:, 1]) / zc + cam['cy']).astype(np.int64)
    inside = (x >= 0) & (x < W) & (y >= 0) & (y < H)
    x, y, zc, N = x[inside], y[inside], zc[inside], N[inside]
    if len(x) == 0:
        return (
            np.full((H, W), np.nan, np.float32),
            np.zeros((H, W, 3), np.float32),
            np.zeros((H, W), bool),
            {'bbox_fill': 0.0, 'interior_holes': 1.0, 'samples': int(total), 'front_tris': int(len(tris))},
        )
    pix = y * W + x
    depth = np.full(H * W, np.inf, np.float32)
    np.minimum.at(depth, pix, zc.astype(np.float32))
    # normal of the winning sample per pixel: sort by (pixel, depth), take first
    order = np.lexsort((zc, pix))
    ps, ns = pix[order], N[order]
    first = np.ones(len(ps), bool)
    first[1:] = ps[1:] != ps[:-1]
    nrm = np.zeros((H * W, 3), np.float32)
    nrm[ps[first]] = ns[first]
    mask = np.isfinite(depth)
    depth[~mask] = np.nan
    m2 = mask.reshape(H, W)
    ys, xs = np.nonzero(m2)
    stats = {
        'bbox_fill': 0.0,
        'interior_holes': 1.0,
        'samples': int(total),
        'front_tris': int(len(tris)),
        'samples_per_covered_px': round(float(len(x)) / max(int(m2.sum()), 1), 1),
    }
    if len(xs) > 4:
        import cv2

        y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
        box = m2[y0:y1, x0:x1].astype(np.uint8)
        closed = cv2.morphologyEx(box, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
        stats['bbox_fill'] = round(float(box.mean()), 4)
        stats['interior_holes'] = round(float(((closed - box) > 0).mean()), 4)
    return depth.reshape(H, W), nrm.reshape(H, W, 3), m2, stats


def _plate_pngs(depth, normal, mask, out_dir, stem):
    """depth.png (near = WHITE, normalised over the face only) and normal.png
    ((n*0.5+0.5)*255, camera space, background 128/128/255) — the conventions
    geom/conditioning.py:25-27 and :132 state, so these plates drop straight
    into a ControlNet the rest of the stack already feeds."""
    import numpy as np
    import cv2

    d = np.zeros(depth.shape, np.uint8)
    if mask.any():
        z = depth[mask]
        lo, hi = float(np.nanmin(z)), float(np.nanmax(z))
        span = max(hi - lo, 1e-6)
        d[mask] = np.clip(255.0 * (1.0 - (z - lo) / span), 0, 255).astype(np.uint8)
    n = np.full(normal.shape, 0.0, np.float32)
    n[..., 2] = 1.0
    n[mask] = normal[mask]
    n8 = np.clip((n * 0.5 + 0.5) * 255.0, 0, 255).astype(np.uint8)
    os.makedirs(out_dir, exist_ok=True)
    dp = os.path.join(out_dir, f'{stem}_depth.png')
    npth = os.path.join(out_dir, f'{stem}_normal.png')
    cv2.imwrite(dp, d)
    cv2.imwrite(npth, cv2.cvtColor(n8, cv2.COLOR_RGB2BGR))
    return dp, npth


def expression_plates(video, out_dir=None, stride=2, max_frames=40, identity=None, log=print):
    """Driver clip -> per-frame ICT face depth + normal plates in the SOURCE
    frame, plus a receipt with the per-frame landmark reprojection error.

    `identity` (100 ICT weights) is optional: with none, the generic neutral
    face carries the expression, which is what a CONTROL plate wants — the
    plate constrains where the eyelids and lips are, not whose face it is.
    """
    import numpy as np
    from zyg_workflows.geom import ict_face as I

    t0 = time.time()
    name = os.path.splitext(os.path.basename(video))[0]
    out_dir = out_dir or os.path.join(PLATE_ROOT, name)
    os.makedirs(out_dir, exist_ok=True)
    drv = extract_driver(video, os.path.join(out_dir, 'driver.json'), stride=stride, max_frames=max_frames, log=log)
    m = I.model()
    lm_idx = np.asarray(m['landmarks68'])
    _mask, tris = _ict_face_region()
    corr = correspondence()['mp468_to_ibug68']

    ledger = {'plated': [], 'no_face': [], 'declined': [], 'failed': []}
    rows = []
    for fr in drv['frames']:
        stem = f'f{fr["frame"]:04d}'
        if not fr.get('ok'):
            ledger['no_face'].append(stem)
            continue
        W, H = fr['size']
        lm478 = np.asarray(fr['landmarks'], np.float32)
        if lm478.shape[0] < 468:
            ledger['no_face'].append(stem)
            continue
        target = lm478[corr][:, :2]
        ex = I.ex_weights_from_blendshapes(fr.get('blendshapes') or {})
        try:
            verts = I.deform(id_w=identity, ex_w=ex)
            cam, rms = _pose_ict(target, W, H, verts, lm_idx, yaw0=fr.get('yaw'))
            depth, nrm, msk, rstats = _raster(verts / 100.0, tris, cam, W, H)
        except Exception as exc:
            ledger['failed'].append(stem)
            rows.append({'frame': fr['frame'], 'state': 'failed', 'reason': f'{type(exc).__name__}: {exc}'})
            continue
        if not msk.any():
            ledger['declined'].append(stem)
            rows.append(
                {'frame': fr['frame'], 'state': 'declined', 'reason': 'head projects entirely outside the frame'}
            )
            continue
        dp, npth = _plate_pngs(depth, nrm, msk, out_dir, stem)
        ledger['plated'].append(stem)
        top = sorted((fr.get('blendshapes') or {}).items(), key=lambda kv: -kv[1])[:4]
        rows.append(
            {
                'frame': fr['frame'],
                'state': 'plated',
                'depth': dp,
                'normal': npth,
                'reproj_rms_px': round(cam['rms_px'], 2),
                'reproj_nojaw_rms_px': round(cam['nojaw_rms_px'], 2),
                'coverage_px': int(msk.sum()),
                'raster': rstats,
                'expression_l1': round(float(np.abs(ex).sum()), 3),
                'top_blendshapes': [[k, round(v, 3)] for k, v in top],
                'cam': {k: (round(v, 4) if isinstance(v, float) else v) for k, v in cam.items()},
            }
        )
        log(
            f'[head_fit] plate {stem}: reproj {cam["rms_px"]:.1f} px '
            f'(no-jaw {cam["nojaw_rms_px"]:.1f}), {int(msk.sum())} px covered, '
            f'interior holes {rstats["interior_holes"] * 100:.2f}% '
            f'(bbox fill {rstats["bbox_fill"]:.2f}, '
            f'{rstats["samples_per_covered_px"]} samples/px), '
            f'top {top[0][0] if top else "-"}'
        )

    good = [r for r in rows if r['state'] == 'plated']

    def rms(xs):
        return round(float(np.sqrt(np.mean(np.asarray(xs, 'float64') ** 2))), 2) if xs else None

    receipt = {
        'video': video,
        'out_dir': out_dir,
        'stride': stride,
        'max_frames': max_frames,
        'identity': 'generic neutral (control plate)' if identity is None else 'fitted ICT identity',
        'ledger': {k: len(v) for k, v in ledger.items()},
        'n_plated': len(good),
        'reproj_rms_px': rms([r['reproj_rms_px'] for r in good]),
        'reproj_nojaw_rms_px': rms([r['reproj_nojaw_rms_px'] for r in good]),
        'interior_holes_mean': round(float(np.mean([r['raster']['interior_holes'] for r in good])), 4)
        if good
        else None,
        'interior_holes_max': round(float(np.max([r['raster']['interior_holes'] for r in good])), 4) if good else None,
        'bbox_fill_mean': round(float(np.mean([r['raster']['bbox_fill'] for r in good])), 4) if good else None,
        'samples_per_covered_px_mean': round(float(np.mean([r['raster']['samples_per_covered_px'] for r in good])), 1)
        if good
        else None,
        'coverage_px_median': int(np.median([r['coverage_px'] for r in good])) if good else None,
        'expression_l1_mean': round(float(np.mean([r['expression_l1'] for r in good])), 3) if good else None,
        'conventions': 'depth near=white normalised over the face only; normal '
        '(n*0.5+0.5)*255 camera space, background (128,128,255) '
        '— geom/conditioning.py:25-27, :132',
        'frames': rows,
        'elapsed_s': round(time.time() - t0, 1),
        'date': time.strftime('%Y-%m-%dT%H:%M:%S'),
    }
    with open(os.path.join(out_dir, 'plates.json'), 'w', encoding='utf-8') as f:
        json.dump(receipt, f, indent=1)
    log(
        f'[head_fit] plates -> {out_dir}: {len(good)} plated, '
        f'reproj rms {receipt["reproj_rms_px"]} px '
        f'(no-jaw {receipt["reproj_nojaw_rms_px"]}), interior holes mean '
        f'{receipt["interior_holes_mean"]} max {receipt["interior_holes_max"]}, '
        f'ledger {receipt["ledger"]}'
    )
    return receipt
