# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""anny_animate.py — the fitted body, animated, into the VACE control channel (2026-08-04).

RUN:
    python3 -m zyg_workflows.geom.anny_animate <char_id> --from cell_24 --to cell_26 \\
        [--frames 41] [--char-asset char_abel]

THE CHAIN THIS COMPLETES. The whole geometry programme exists because the VACE control
channel used to carry flat grey 127 wherever a character or prop lived, and the model
re-invented whatever it wasn't told — measured as prop fidelity ~0 by frame 80 and
identity decay by frame 200. The tree fixed it for the set. This closes it for PEOPLE:

    anny_fit (per cell)  ->  pose_aa + camera + global rotation, phenotype LOCKED to the
                             character's declared build (12y/1.52m for Abel)
    interpolate          ->  per-bone axis-angle lerp between two fitted poses, smoothstep
                             timing; camera and global rotation lerp alongside
    render (per frame)   ->  the posed 13,718-vert body rasterised painter's-algorithm
                             into a DEPTH map (near = white) + skeleton — no estimator
    vace_control.build   ->  ctrl_XXXXX.png sequence + the grey-127 audit

Every frame RE-STATES the body. Nothing asks the video model to remember a character
across windows, so there is nothing to forget — the same cure as the tree, applied to
the cast.

HONEST SCOPE. Axis-angle lerp between two REAL fitted poses is correct interpolation of
a coarse fit — it is not choreography, and nobody should read acting into it. It is the
control-channel plumbing, proven end to end with real fitted data.
"""

import argparse
import glob
import json
import os
import sys

import numpy as np

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None

from .char_mesh import OUT_ROOT

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


def _smoothstep(t):
    return t * t * (3.0 - 2.0 * t)


def render_depth(verts, faces, cam, glob_R, W, H, camera_model='ortho'):
    """Painter's-algorithm depth render of the posed body. near = white.

    Supports both camera models: legacy orthographic [s,cx,cy] and pinhole [f,tz,cx,cy]
    (anny_fit v2.1) — the pair being animated must share one model.
    """
    p = verts @ glob_R.T
    if camera_model == 'pinhole':
        f, tz, cx, cy = cam
        z_c = np.clip(p[:, 1] + tz, 0.25, None)
        x = f * p[:, 0] / z_c + cx
        y = f * (-p[:, 2]) / z_c + cy
    else:
        x = p[:, 0] * cam[0] + cam[1]
        y = -p[:, 2] * cam[0] + cam[2]
    z = p[:, 1]
    fz = z[faces].mean(axis=1)
    order = np.argsort(-fz)  # far first, near painted last
    lo, hi = np.percentile(z, 2), np.percentile(z, 98)
    shade = (1.0 - np.clip((fz - lo) / max(hi - lo, 1e-6), 0, 1)) * 235 + 20

    img = np.zeros((H, W), np.uint8)
    pts = np.stack([x, y], -1).astype(np.int32)
    for fi in order:
        quad = pts[faces[fi]]
        if quad[:, 0].max() < 0 or quad[:, 0].min() >= W:
            continue
        if quad[:, 1].max() < 0 or quad[:, 1].min() >= H:
            continue
        cv2.fillConvexPoly(img, quad, int(shade[fi]))
    return img


def run(
    char_id,
    cell_a,
    cell_b,
    frames=41,
    char_asset='',
    fps_note=17,
    body=None,
    legacy_phenotype=False,
    ctrl_name='vace_ctrl',
    pose_char_id=None,
    fit_name='anny_fit.json',
):
    """Interpolate two fitted poses and render the control track.

    `body` names the REGISTERED body to animate — the phenotype, local morphs and
    bone scales that were issued, hash-checked against the recorded cage. Before
    2026-09-02 this function had no such argument and built its body from a
    height-only calibration, so the 41-frame abel track carried gender 1.0 /
    height 0.9702 against the registered abel's 0.0 / 0.8873.

    `pose_char_id` lets the POSES come from one character and the BODY from another
    (`--body cornelis --pose-char c3345deb5bde`). That is not a feature for
    production; it exists to build the deliberately WRONG-body track the control-path
    receipt needs as its negative arm. A track built that way says so in its report.
    """
    import torch
    from .anny_fit import _rotmat
    from . import phenotype as PH

    root = os.path.join(OUT_ROOT, char_id)
    pose_root = os.path.join(OUT_ROOT, pose_char_id or char_id)
    fits = {}
    for c in (cell_a, cell_b):
        p = os.path.join(pose_root, c, fit_name)
        if not os.path.exists(p):
            raise SystemExit('%s has no anny_fit.json — run geom.anny_fit first' % c)
        fits[c] = json.load(open(p))
        if 'pose_aa' not in fits[c]:
            raise SystemExit('%s fit predates pose saving — refit' % c)

    spec = None
    if body:
        nm = PH.resolve_body_name(body)
        if not nm:
            raise SystemExit('%r does not resolve to a registered body' % body)
        spec = PH.registry_body(nm)
    elif not legacy_phenotype:
        nm = PH.resolve_body_name(char_id) or PH.resolve_body_name(char_asset)
        if nm:
            _zyg_log.info('body: %r resolved from the character; --legacy-phenotype for the old height-only path' % nm)
            spec = PH.registry_body(nm)
    if spec is None:
        spec = PH.spec_for(char_asset=char_asset) or PH.legacy_spec({})
        _zyg_log.info('body: LEGACY — %s' % PH.describe(spec))

    m = PH.body_model(spec)
    S44 = PH.bone_scale_matrix(spec, m)
    faces = m.faces.numpy() if hasattr(m.faces, 'numpy') else np.asarray(m.faces)
    A, B = fits[cell_a], fits[cell_b]
    pose_a = torch.tensor(A['pose_aa'], dtype=torch.float32)
    pose_b = torch.tensor(B['pose_aa'], dtype=torch.float32)
    cam_a, cam_b = np.array(A['camera']), np.array(B['camera'])
    ga, gb = np.array(A['global_aa']), np.array(B['global_aa'])
    W = H = None

    frames_dir = os.path.join(root, 'anim_frames')
    os.makedirs(frames_dir, exist_ok=True)
    for old in glob.glob(os.path.join(frames_dir, '*.png')):
        os.remove(old)

    with open(os.path.join(root, cell_a, 'mesh.json')) as f:
        W, H = json.load(f)['size']

    for i in range(frames):
        t = _smoothstep(i / max(frames - 1, 1))
        pose = pose_a * (1 - t) + pose_b * t
        cam = cam_a * (1 - t) + cam_b * t
        gaa = ga * (1 - t) + gb * t
        with torch.no_grad():
            out = m(**PH.forward_kwargs(spec, pose, model=m, scale44=S44))
            v = out['vertices'][0].to(torch.float32).numpy()
        R = _rotmat(torch.tensor(gaa, dtype=torch.float32)).numpy()
        img = render_depth(v, faces, cam, R, W, H, camera_model=A.get('camera_model', 'ortho'))
        cv2.imwrite(os.path.join(frames_dir, 'frame_%05d.png' % i), img)
        if i % 10 == 0:
            _zyg_log.info('  frame %d/%d' % (i, frames))

    from . import vace_control

    ctrl = os.path.join(root, ctrl_name)
    r = vace_control.build(frames_dir, ctrl, frames=frames)
    audit = vace_control.audit(ctrl)
    _zyg_log.info('  ctrl: %d frames -> %s' % (r['frames'], ctrl))
    _zyg_log.info('  audit: %s (grey fraction %.4f%%)' % (audit['verdict'][:60], audit['grey_fraction_mean'] * 100))

    # contact strip for review
    idxs = [0, frames // 3, 2 * frames // 3, frames - 1]
    strip = np.concatenate(
        [
            cv2.resize(cv2.imread(os.path.join(frames_dir, 'frame_%05d.png' % i)), None, fx=380.0 / H, fy=380.0 / H)
            for i in idxs
        ],
        axis=1,
    )
    # NOT inside `ctrl`: that directory is a frame SEQUENCE read by glob, and a
    # contact strip sitting in it becomes a 42nd 'frame'.
    cv2.imwrite(os.path.join(root, '%s_strip.png' % ctrl_name), strip)
    ph = spec.get('phenotype_kwargs') or {}
    rep_ = {
        'from': cell_a,
        'to': cell_b,
        'frames': frames,
        'phenotype': {k: round(float(v), 4) for k, v in ph.items()},
        'body': {
            'source': spec.get('source'),
            'name': spec.get('name'),
            'cage_vert_sha256': spec.get('cage_vert_sha256_rebuilt'),
            'hash_verified': bool(spec.get('hash_verified')),
            'local_changes': len(spec.get('local_changes') or {}),
            'bone_scales_effective': spec.get('bone_scales_effective') or {},
            'anatomy_layer': spec.get('anatomy_layer') or {},
            'anatomy_layer_applied': False,
            'anatomy_layer_note': PH.ANATOMY_LAYER_NOTE,
            'describe': PH.describe(spec),
        },
        'poses_from_char_id': pose_char_id or char_id,
        'fit_report_used': fit_name,
        'ctrl_dir': ctrl,
        'audit': audit,
    }
    if (pose_char_id and pose_char_id != char_id) or (
        spec.get('name') and PH.resolve_body_name(char_id) and spec.get('name') != PH.resolve_body_name(char_id)
    ):
        rep_['deliberately_wrong_body'] = (
            "the poses are %s's and the body is %r — this track is a NEGATIVE "
            'control, not a deliverable.' % (pose_char_id or char_id, spec.get('name'))
        )
    with open(os.path.join(ctrl, 'anim_report.json'), 'w') as f:
        json.dump(rep_, f, indent=1)
    if ctrl_name == 'vace_ctrl':
        # the historical locations, kept so existing readers do not break
        cv2.imwrite(os.path.join(root, 'anim_strip.png'), strip)
        with open(os.path.join(root, 'anim_report.json'), 'w') as f:
            json.dump(rep_, f, indent=1)
    return audit


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('char_id')
    ap.add_argument('--from', dest='cell_a', required=True)
    ap.add_argument('--to', dest='cell_b', required=True)
    ap.add_argument('--frames', type=int, default=41)
    ap.add_argument('--char-asset', default='')
    ap.add_argument('--body', default='', help='registered body to animate (registry name / char_id / asset)')
    ap.add_argument('--legacy-phenotype', action='store_true', help='the pre-2026-09-02 height-only calibration path')
    ap.add_argument(
        '--ctrl-name',
        default='vace_ctrl',
        help='subdirectory of the character output dir to write the control '
        'frames into; use a new name to avoid overwriting a track',
    )
    ap.add_argument(
        '--pose-char',
        default='',
        help='take the POSES from this char_id while the body comes from --body: the negative-control track',
    )
    ap.add_argument('--fit-name', default='anny_fit.json', help='which per-cell fit report to read the poses from')
    a = ap.parse_args(argv)
    audit = run(
        a.char_id,
        a.cell_a,
        a.cell_b,
        a.frames,
        a.char_asset,
        body=a.body,
        legacy_phenotype=a.legacy_phenotype,
        ctrl_name=a.ctrl_name,
        pose_char_id=a.pose_char or None,
        fit_name=a.fit_name,
    )
    return 0 if audit.get('ok') else 2


if __name__ == '__main__':
    sys.exit(main())
