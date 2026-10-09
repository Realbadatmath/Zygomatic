# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from zyg_workflows.geom.head_fit.cell_fit import run, smoke
from zyg_workflows.geom.head_fit.corr_map import OUT_ROOT, _CREWS, argparse, build_correspondence, json, os, time
from zyg_workflows.geom.head_fit.plates import expression_plates

# ═══════════════════════════════════════════════════════════════════════════
# THE BRIDGE DECISION — is a GNM identity delta worth transferring onto a
# registered anny head?
#
# The bridge is deliberately a DELTA ON ANNY VERTICES, never a mesh swap: anny
# topology and therefore the registry's cage hash contract survive either
# answer, which is the only reason this can be measured at all without asking
# the operator to approve a reissue (S04 owns the registry; this module reads).
#
# The transfer has a cost nobody had measured: the GNM identity delta is defined
# over GNM's crop (skin_exterior at or above the chin landmark, gnm_fit.py:50-57,
# :184-190) and anny's head crop ends somewhere else, so at the neck ring the
# delta must be blended to zero. Whatever displacement the delta still carries
# where the blend forces it to zero is not transferred — it is a SEAM ERROR, a
# smooth ramp standing in for real geometry. Building the bridge is only worth
# it when the identity it delivers is larger than the error it introduces.
# ═══════════════════════════════════════════════════════════════════════════

GNM_FITS = os.path.join(_CREWS, 'data', 'assets', 'gnm_head', 'fits')
BRIDGE_DIR = os.path.join(OUT_ROOT, 'bridge')


def _anny_head_frame(body, log=print):
    """Everything the bridge needs about a registered body's head, in the SAME
    canonical frame gnm_fit fitted in (gnm_fit.anny_head_target) — otherwise the
    stored similarity means nothing.

    Returns dict with verts (original frame), C (the canonicalising
    permutation/sign matrix), centre, head_w, neck_w, core mask, faces.
    """
    import numpy as np
    from zyg_workflows.geom import gnm_fit as GF
    from zyg_workflows.geom import mesh_skeletons as MS
    from zyg_workflows.geom import relief as RELIEF

    p, section = GF.registry_params(body)
    v, faces, _applied = MS._build_mesh(p['phenotype'], p.get('local_changes'), params=p)
    m = MS._model()
    w, bidx = RELIEF.bone_weights(m)
    if w is None:
        raise RuntimeError('anny exposes no skinning weights — cannot crop head')
    labels = [str(b) for b in m.bone_labels]
    head_ids = [labels.index(b) for b in GF.HEAD_BONES if b in labels]
    neck_ids = [labels.index(b) for b in GF.NECK_BONES if b in labels]
    head_w = (np.asarray(w) * np.isin(np.asarray(bidx), head_ids)).sum(axis=1)
    neck_w = (np.asarray(w) * np.isin(np.asarray(bidx), neck_ids)).sum(axis=1)
    core = (head_w > GF.HEAD_W_MIN) & (neck_w < GF.NECK_W_MAX)
    spans = v.max(0) - v.min(0)
    up = int(np.argmax(spans))
    sign = 1.0 if v[core].mean(0)[up] >= v.mean(0)[up] else -1.0
    axes = [0, 1, 2]
    axes.remove(up)
    C = np.zeros((3, 3))
    C[0, axes[0]] = 1.0
    C[1, up] = sign
    C[2, axes[1]] = 1.0
    centre = (v[core] @ C.T).mean(0)
    log(
        f'[head_fit] {body} ({section}): {v.shape[0]} verts, head core '
        f'{int(core.sum())}, stature {float(spans[up]):.3f} m'
    )
    return {
        'body': body,
        'section': section,
        'verts': v.astype('float64'),
        'faces': np.asarray(faces),
        'C': C,
        'centre': centre,
        'head_w': head_w,
        'neck_w': neck_w,
        'core': core,
    }


def _blend_weights(A, smooth=12, log=print):
    """Per-vertex transfer weight: 1 on the head core, 0 off the head, and a
    Laplacian-smoothed ramp between. `smooth` iterations of umbrella smoothing
    over the anny mesh's own edge graph — a hard core/band step would put the
    seam error in a single ring of faces instead of spreading it, which flatters
    the measurement."""
    import numpy as np
    from scipy import sparse

    faces = A['faces']
    n = len(A['verts'])
    q = faces
    edges = []
    k = q.shape[1]
    for i in range(k):
        edges.append(np.stack([q[:, i], q[:, (i + 1) % k]], 1))
    E = np.concatenate(edges, 0)
    E = np.concatenate([E, E[:, ::-1]], 0)
    Adj = sparse.coo_matrix((np.ones(len(E)), (E[:, 0], E[:, 1])), shape=(n, n)).tocsr()
    deg = np.asarray(Adj.sum(1)).ravel()
    deg[deg == 0] = 1.0
    w = np.zeros(n)
    w[A['core']] = 1.0
    fixed_one = A['core']
    fixed_zero = A['head_w'] < 0.02  # unambiguously not head
    for _ in range(int(smooth)):
        w = np.asarray(Adj @ w).ravel() / deg
        w[fixed_one] = 1.0
        w[fixed_zero] = 0.0
    band = (w > 0.02) & (w < 0.98)
    log(
        f'[head_fit] blend: core {int(fixed_one.sum())}, band {int(band.sum())}, '
        f'off-head {int(fixed_zero.sum())} of {n} verts'
    )
    return w, band


def bridge_decision(bodies=('male', 'female', 'abel', 'cornelis'), log=print):
    """Measure the identity a GNM delta delivers against the seam error the
    transfer costs, per body, and decide. Writes output/head_fit/bridge/."""
    import numpy as np
    from zyg_workflows.geom import gnm_head as GH
    from zyg_workflows.geom import gnm_fit as GF
    from scipy.spatial import cKDTree

    os.makedirs(BRIDGE_DIR, exist_ok=True)
    fit_mask_np, _face_np = GF.gnm_fit_mask(log=log)
    mean_v = GH.vertices_for(GH.neutral_params())
    rows = []
    for body in bodies:
        fpath = os.path.join(GNM_FITS, body, 'fit.json')
        if not os.path.isfile(fpath):
            rows.append({'body': body, 'state': 'unmeasurable', 'reason': f'no Phase-1 fit at {fpath}'})
            continue
        try:
            fit = json.load(open(fpath, encoding='utf-8'))
            A = _anny_head_frame(body, log=log)
            w, band = _blend_weights(A, log=log)
            idn = np.asarray(fit['identity'], dtype='float32')
            fitted_v = GH.vertices_for({**GH.neutral_params(), 'identity': idn})
            sim = fit['similarity']
            import roma
            import torch

            R = roma.rotvec_to_rotmat(torch.tensor(sim['rotvec'], dtype=torch.float32)).numpy()
            s = float(np.exp(sim['log_scale']))
            t = np.asarray(sim['translation'], dtype='float64')
            # GNM geometry in the anny CANONICAL frame (the frame gnm_fit fitted in)
            src_mean = s * (mean_v.astype('float64') @ R.T) + t
            # a DELTA carries no translation
            delta_gnm = s * ((fitted_v - mean_v).astype('float64') @ R.T)
            keep = fit_mask_np
            tree = cKDTree(src_mean[keep])
            anny_c = (A['verts'] @ A['C'].T) - A['centre']
            sel = w > 0.02
            d_nn, i_nn = tree.query(anny_c[sel], k=1)
            delta_sel = delta_gnm[keep][i_nn]  # canonical frame
            mag = np.linalg.norm(delta_sel, axis=1) * 1000.0  # mm
            # SEAM ERROR: the displacement the falloff throws away. Every vertex
            # keeps only w * delta, so (1-w) * |delta| is geometry the transfer
            # asserts is zero and is not.
            wsel = w[sel]
            dropped = (1.0 - wsel) * mag
            band_sel = band[sel]
            seam_rms = float(np.sqrt((dropped[band_sel] ** 2).mean())) if band_sel.any() else 0.0
            seam_max = float(dropped[band_sel].max()) if band_sel.any() else 0.0
            core_sel = wsel > 0.98
            core_delta_rms = float(np.sqrt((mag[core_sel] ** 2).mean())) if core_sel.any() else 0.0
            nn_rms_mm = float(np.sqrt((d_nn**2).mean())) * 1000.0
            gain = float(fit['metrics']['identity_gain_mm'])
            # topology contract: a delta cannot change vertex count or faces
            moved = A['verts'].copy()
            moved[sel] += (wsel[:, None] * delta_sel) @ A['C']  # back to anny frame
            topo_ok = bool(moved.shape == A['verts'].shape and np.isfinite(moved).all())
            verdict = 'BUILD' if gain > seam_rms else 'REFUSE'
            rows.append(
                {
                    'body': body,
                    'state': 'measured',
                    'verdict': verdict,
                    'identity_gain_mm': round(gain, 3),
                    'seam_error_rms_mm': round(seam_rms, 3),
                    'seam_error_max_mm': round(seam_max, 3),
                    'core_delta_rms_mm': round(core_delta_rms, 3),
                    'ratio_gain_over_seam': round(gain / max(seam_rms, 1e-9), 3),
                    'nn_transfer_rms_mm': round(nn_rms_mm, 3),
                    'n_core': int((w > 0.98).sum()),
                    'n_band': int(band.sum()),
                    'n_verts': int(len(A['verts'])),
                    'phase1_face_rms_mm': round(float(fit['metrics']['face_fw_rms_mm']), 3),
                    'phase1_mean_head_rms_mm': round(float(fit['metrics']['mean_head_face_rms_mm']), 3),
                    'phase1_clip_hits': int(fit['metrics']['clip_hits']),
                    'phase1_coeff_absmax': round(float(fit['metrics']['coeff_absmax']), 3),
                    'topology_preserved': topo_ok,
                    'fit_date': fit.get('date'),
                }
            )
            log(
                f'[head_fit] BRIDGE {body}: identity gain {gain:+.2f} mm vs seam error '
                f'{seam_rms:.2f} mm rms (max {seam_max:.2f}) -> {verdict}  '
                f'[core delta {core_delta_rms:.2f} mm, nn transfer {nn_rms_mm:.2f} mm, '
                f'topology preserved {topo_ok}]'
            )
        except Exception as exc:
            rows.append({'body': body, 'state': 'failed', 'reason': f'{type(exc).__name__}: {exc}'})
            log(f'[head_fit] BRIDGE {body} FAILED: {type(exc).__name__}: {exc}')

    measured = [r for r in rows if r.get('state') == 'measured']
    build = [r for r in measured if r['verdict'] == 'BUILD']
    doc = {
        'question': 'transfer the fitted-minus-mean GNM identity delta onto a '
        'registered anny head, blended to zero across the neck ring?',
        'rule': 'BUILD only where identity_gain_mm > seam_error_rms_mm, per body',
        'identity_gain_source': 'data/assets/gnm_head/fits/<body>/fit.json — the '
        'Phase-1 mesh-ICP gain over the MEAN head, which is '
        'itself the null for that number',
        'seam_error_definition': '(1 - blend_weight) * |delta| over the blend band: '
        'the displacement the falloff discards, i.e. real '
        'geometry the transfer replaces with a smooth ramp',
        'anatomy_layer_written': False,
        'decision': ('BUILD' if build and len(build) == len(measured) else 'REFUSE' if not build else 'SPLIT'),
        'bodies': rows,
        'date': time.strftime('%Y-%m-%dT%H:%M:%S'),
    }
    with open(os.path.join(BRIDGE_DIR, 'bridge_decision.json'), 'w', encoding='utf-8') as f:
        json.dump(doc, f, indent=1)
    log('')
    log(f'{"body":10s} {"gainMM":>8s} {"seamRMS":>8s} {"seamMax":>8s} {"coreDelta":>10s} {"ratio":>7s}  verdict')
    for r in measured:
        log(
            f'{r["body"]:10s} {r["identity_gain_mm"]:+8.2f} {r["seam_error_rms_mm"]:8.2f} '
            f'{r["seam_error_max_mm"]:8.2f} {r["core_delta_rms_mm"]:10.2f} '
            f'{r["ratio_gain_over_seam"]:7.2f}  {r["verdict"]}'
        )
    log(f'[head_fit] BRIDGE DECISION: {doc["decision"]} -> {os.path.join(BRIDGE_DIR, "bridge_decision.json")}')
    return doc


def _cli():
    ap = argparse.ArgumentParser(description='MediaPipe -> GNM head identity fit')
    sub = ap.add_subparsers(dest='cmd')
    sub.add_parser('corr', help='derive + cache the MP468->iBUG68 map')
    b = sub.add_parser('bridge', help='measure identity gain vs seam error')
    b.add_argument('--bodies', default='male,female,abel,cornelis')
    pl = sub.add_parser('plates', help='driver clip -> ICT face depth/normal plates')
    pl.add_argument('video')
    pl.add_argument('--out', default=None)
    pl.add_argument('--stride', type=int, default=2)
    pl.add_argument('--max-frames', type=int, default=40)
    r = sub.add_parser('run')
    r.add_argument('--chars', default='')
    r.add_argument('--holdout-every', type=int, default=3)
    r.add_argument('--jaw-weight', type=float, default=None)
    sub.add_parser('smoke')
    args = ap.parse_args()
    if args.cmd == 'corr':
        build_correspondence()
        return 0
    if args.cmd == 'bridge':
        bridge_decision(tuple(b.strip() for b in args.bodies.split(',') if b.strip()))
        return 0
    if args.cmd == 'plates':
        expression_plates(args.video, out_dir=args.out, stride=args.stride, max_frames=args.max_frames)
        return 0
    if args.cmd == 'smoke':
        return 0 if smoke() else 1
    if args.cmd == 'run':
        run(
            [c.strip() for c in args.chars.split(',') if c.strip()] or None,
            holdout_every=args.holdout_every,
            jaw_weight=args.jaw_weight,
        )
        return 0
    ap.print_help()
    return 0
