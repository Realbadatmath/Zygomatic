# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The character artefacts: preview renderer, mesh3d/GLB export,
measurement, the registry, write protection and the aux hash ledger.

Moved verbatim out of the old single-file mesh_skeletons.py (lines 1658-1958).
"""

import hashlib
import json
import os
import stat
import time

import numpy as np

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None

from zyg_workflows.geom.mesh_skeletons.spec import ANTHRO_REPORT_FILE, DISPLAY_SUBDIV, MESH3D_SUBDIV, REGISTRY, ROOT

from zyg_workflows.geom.mesh_skeletons.rig import _sha256

from zyg_workflows.geom.mesh_skeletons.anatomy import _subdivide


# Preview renderer palette (BGR). Clay surface + a darker wireframe that reads as the
# geometry grid — the whole point of these previews is READABLE GEOMETRY.
_BG_BGR = (19, 15, 13)
_CLAY_BGR = np.array([192, 200, 205], np.float32)
_EDGE_BGR = np.array([96, 84, 74], np.float32)


def _paint(p, faces, win, out_wh, ss, edge_mask=None):
    """Rasterise one orthographic view at maximum quality.

    Painter's algorithm over back-face-culled quads; flat clay shading from two lights
    (key + fill + ambient, gamma-lifted); the wireframe drawn per face in the same
    depth order, so nearer surface correctly overdraws farther grid lines; the whole
    canvas supersampled ss× and area-downsampled for clean anti-aliasing.

    edge_mask (F,4) bool selects which of each face's edges belong to the CAGE grid —
    on a subdivided surface only those are drawn, giving a smooth body with the
    original quad topology readable on top.
    """
    x0, x1, z0, z1 = win
    W, H = out_wh
    Ws, Hs = W * ss, H * ss
    s = min(Ws / max(x1 - x0, 1e-9), Hs / max(z1 - z0, 1e-9))
    X = (p[:, 0] - (x0 + x1) / 2.0) * s + Ws / 2.0
    Y = -(p[:, 2] - (z0 + z1) / 2.0) * s + Hs / 2.0
    pts = np.stack([X, Y], -1).astype(np.int32)

    e1 = p[faces[:, 1]] - p[faces[:, 0]]
    e2 = p[faces[:, 2]] - p[faces[:, 0]]
    nrm = np.cross(e1, e2)
    nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-9)
    keep = nrm[:, 1] < 0.0  # camera looks along +y
    fx, fy = X[faces], Y[faces]
    keep &= (fx.max(1) >= 0) & (fx.min(1) <= Ws) & (fy.max(1) >= 0) & (fy.min(1) <= Hs)
    idx = np.nonzero(keep)[0]
    idx = idx[np.argsort(-p[:, 1][faces[idx]].mean(1))]

    # raking key (tuned 2026-08-05): a flat frontal key hides surface relief; this
    # side-biased key is what makes muscle/anatomy definition actually visible
    l1 = np.array([0.70, -0.45, 0.45])
    l1 /= np.linalg.norm(l1)
    l2 = np.array([-0.35, -0.75, 0.10])
    l2 /= np.linalg.norm(l2)
    lam = 0.13 + 0.72 * np.clip(nrm @ l1, 0, 1) + 0.22 * np.clip(nrm @ l2, 0, 1)
    lam = np.clip(lam, 0, 1) ** (1 / 1.8)
    fill_c = np.clip(_CLAY_BGR[None] * lam[:, None], 0, 255).astype(np.uint8)
    edge_c = np.clip(_EDGE_BGR[None] * (0.55 + 0.45 * lam[:, None]), 0, 255).astype(np.uint8)

    img = np.full((Hs, Ws, 3), _BG_BGR, np.uint8)
    th = max(1, int(round(ss * 0.75)))
    for fi in idx:
        fq = faces[fi]
        q = pts[fq]
        fc, ec = fill_c[fi], edge_c[fi]
        cv2.fillConvexPoly(img, q, (int(fc[0]), int(fc[1]), int(fc[2])), cv2.LINE_AA)
        ecol = (int(ec[0]), int(ec[1]), int(ec[2]))
        if edge_mask is None:
            cv2.polylines(img, [q], True, ecol, th, cv2.LINE_AA)
        else:
            for i in np.nonzero(edge_mask[fi])[0]:
                cv2.line(img, tuple(q[i]), tuple(q[(i + 1) % 4]), ecol, th, cv2.LINE_AA)
    return cv2.resize(img, (W, H), interpolation=cv2.INTER_AREA)


def _edge_mask(faces, cage_edges):
    """(F,4) bool: which edge of each face lies on the cage grid."""
    N = int(faces.max()) + 1
    keys = set((int(a) * N + int(b)) for a, b in cage_edges)
    mask = np.zeros((len(faces), 4), bool)
    for fi in range(len(faces)):
        q = faces[fi]
        for i in range(4):
            a, b = int(q[i]), int(q[(i + 1) % 4])
            if a > b:
                a, b = b, a
            if a * N + b in keys:
                mask[fi, i] = True
    return mask


def _shaded_views(v, faces, out_dir, height_px=1600, ss=2, yaws=(0, 45, 90, 180), subdiv=None):
    """Full-body views (front / three-quarter / side / back) + head close-ups.

    Rendered from the SUBDIVIDED limit surface (smooth, no display faceting) with the
    cage's quad grid overlaid. The close-ups exist because the head carries the densest
    geometry — at full-body framing its grid is sub-pixel; at head framing every quad
    is readable. Pass subdiv=(sv, sf, cage) to reuse a computed subdivision.
    """
    os.makedirs(out_dir, exist_ok=True)
    sv, sf, cage = subdiv if subdiv is not None else _subdivide(v, faces)
    emask = _edge_mask(sf, cage)
    c = sv.mean(axis=0)
    specs = [('view_%03d' % y, y, None) for y in yaws] + [('head_%03d' % y, y, (0.845, 1.015)) for y in (0, 45)]
    paths = []
    for name, yaw, foc in specs:
        a = np.radians(yaw)
        R = np.array([[np.cos(a), np.sin(a), 0], [-np.sin(a), np.cos(a), 0], [0, 0, 1]], np.float32)
        p = (sv - c) @ R.T
        if foc is None:
            sel, m = p, 0.06
        else:
            zl, zh = p[:, 2].min(), p[:, 2].max()
            span = zh - zl
            sel = p[(p[:, 2] >= zl + foc[0] * span) & (p[:, 2] <= zl + foc[1] * span)]
            m = 0.10
        x0, x1 = float(sel[:, 0].min()), float(sel[:, 0].max())
        z0, z1 = float(sel[:, 2].min()), float(sel[:, 2].max())
        dx, dz = x1 - x0, z1 - z0
        win = (x0 - dx * m, x1 + dx * m, z0 - dz * m, z1 + dz * m)
        W = int(round(height_px * (0.62 if foc is None else 0.85)))
        img = _paint(p, sf, win, (W, height_px), ss, emask)
        path = os.path.join(out_dir, name + '.png')
        _imwrite(path, img)
        paths.append(os.path.relpath(path, ROOT))
    return paths


def _export_mesh3d(subdiv, path):
    """Geometry for the GUI's interactive 3D viewer: the SUBDIVIDED limit surface
    (smooth body) with the cage's TRUE QUAD EDGES as the grid.

    BINARY format (mesh3d.bin) — at subdiv 3 this is ~33MB vs an unusable 60MB+ of
    JSON: magic 'ZM3D' + uint32 version,nv,ntri,nedge + float32 v[nv*3]
    + uint32 tri[ntri*3] + uint32 edge[nedge*2], little-endian, written atomically."""
    sv, sf, cage = subdiv
    tris = np.concatenate([sf[:, [0, 1, 2]], sf[:, [0, 2, 3]]]).astype(np.uint32)
    v32 = sv.astype(np.float32)
    e32 = cage.astype(np.uint32)
    head = b'ZM3D' + np.array([1, len(v32), len(tris), len(e32)], np.uint32).tobytes()
    tmp = path + '.tmp'
    with open(tmp, 'wb') as f:
        f.write(head)
        f.write(v32.tobytes())
        f.write(tris.tobytes())
        f.write(e32.tobytes())
    os.replace(tmp, path)
    return os.path.relpath(path, ROOT)


def _emit_visuals(v, faces, d):
    """Everything the operator sees: previews (subdiv 2) + 3D viewer geometry
    (subdiv 3, continued from the level-2 result with the cage grid preserved).
    Returns (views, mesh3d_relpath, measured_display, measured_mesh3d)."""
    sub2 = _subdivide(v, faces, DISPLAY_SUBDIV)
    views = _shaded_views(v, faces, d, subdiv=sub2)
    sub3 = _subdivide(sub2[0], sub2[1], MESH3D_SUBDIV - DISPLAY_SUBDIV, seed_cage=sub2[2])
    m3 = _export_mesh3d(sub3, os.path.join(d, 'mesh3d.bin'))
    stale = os.path.join(d, 'mesh3d.json')
    if os.path.exists(stale):
        os.remove(stale)
    return views, m3, _measure(sub2[0]), _measure(sub3[0])


def _export_glb(v, faces, path):
    import trimesh

    tris = np.concatenate([faces[:, [0, 1, 2]], faces[:, [0, 2, 3]]], axis=0)
    trimesh.Trimesh(vertices=v.astype(np.float64), faces=tris, process=False).export(path)
    return path


def _measure(v):
    return {
        'height_m': round(float(v[:, 2].max() - v[:, 2].min()), 4),
        'span_x_m': round(float(v[:, 0].max() - v[:, 0].min()), 4),
        'span_y_m': round(float(v[:, 1].max() - v[:, 1].min()), 4),
        'vertices': int(len(v)),
    }


def _vert_sha(v):
    """Content hash of the cage vertices (4dp) — catches library drift that keeps the
    bounding box but moves interior geometry, which bbox gates cannot see.

    `+ 0.0` canonicalizes IEEE signed zeros: anny's parallel skinning produces
    midline coordinates of ±5e-17 whose SIGN depends on torch's thread count, and a
    rounded -0.0 vs +0.0 differ in tobytes(). Without this, the same recipe hashes
    differently per thread count (measured: three distinct shas at 1/4/16 threads)
    and the refresh gate fails spuriously in any differently-threaded process."""
    return hashlib.sha256((np.round(np.asarray(v, np.float64), 4) + 0.0).tobytes()).hexdigest()


def _registry():
    if os.path.exists(REGISTRY):
        with open(REGISTRY) as f:
            return json.load(f)
    return {'originals': {}, 'derived': {}}


def _save_registry(reg):
    reg['updated'] = time.strftime('%Y-%m-%dT%H:%M:%S')
    _atomic_json(REGISTRY, reg, indent=1)


def _write_protect(d):
    """Files read-only AND the directory itself 555 — without the dir lock, 444 files
    can simply be unlinked and replaced, which no file-mode protects against."""
    for fn in os.listdir(d):
        p = os.path.join(d, fn)
        if os.path.isfile(p):
            os.chmod(p, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    # noqa below: 0o555 is the POINT of _write_protect — it REMOVES write from the issued
    # directory so its 0o444 files cannot be unlinked and replaced. Nothing is granted here.
    os.chmod(d, stat.S_IRUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)  # noqa: S103  write-protect, see comment above


def _write_enable(d):
    """Undo the protection for a deliberate --force re-issue only."""
    if not os.path.isdir(d):
        return
    os.chmod(d, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)  # noqa: S103  0o755 is the ordinary directory mode this undo restores; write stays owner-only
    for fn in os.listdir(d):
        p = os.path.join(d, fn)
        if os.path.isfile(p):
            os.chmod(p, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)


def _imwrite(path, img):
    """cv2.imwrite returns False instead of raising — a silently-registered missing
    preview is exactly the failure mode we refuse to have."""
    if not cv2.imwrite(path, img):
        raise IOError('imwrite failed: %s' % path)


def _atomic_json(path, doc, **kw):
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(doc, f, **kw)
    os.replace(tmp, path)


def _aux_hashes(d, previews, extra=('mesh3d.bin', 'params.json', ANTHRO_REPORT_FILE)):
    """sha256 over everything the GUI DISPLAYS, not just the GLB — the immutability
    badge must cover the operator's actual visual surface.

    anthro_report.json is in the set because the operator reads a verdict off it: a
    tampered report is exactly as misleading as a tampered preview. Files that do not
    exist are skipped, so an entry issued before the gates existed still verifies.

    RE-RECORDING IS NOT VERIFICATION. Callers that re-record this set must first pass the
    files they did NOT themselves rewrite through _aux_assert_unrewritten_intact() — see
    the comment there. Re-recording a hash for a file you did not regenerate adopts
    whatever is on disk and silences the alarm for a file nobody checked."""
    out = {}
    for rel in list(previews or []):
        out[os.path.basename(rel)] = _sha256(os.path.join(ROOT, rel))
    for fn in extra:
        p = os.path.join(d, fn)
        if os.path.exists(p):
            out[fn] = _sha256(p)
    return out


def _aux_assert_unrewritten_intact(d, recorded, rewritten, what):
    """Refuse to re-record the aux hash set over a file this caller did not regenerate.

    THE DEFECT THIS CLOSES (2026-08-05): `refresh_previews()` re-renders the previews,
    mesh3d.bin and params.json, then re-records the WHOLE aux set — which since
    anthro_report.json joined that set includes a file it never touches. A corrupt or
    edited report was flagged by `verify`, and the next routine, visual-only
    `refresh-previews` made the alarm disappear while the bad file stayed on disk. The
    same shape exists in `gate_registered()`, which regenerates params.json and the
    report but not the previews or mesh3d.bin.

    So: a re-record is only honest for files the caller actually rewrote. For everything
    else the recorded hash must still match, and if it does not, that is the immutability
    alarm doing its job — raise, leave the entry exactly as it was, and let `verify` keep
    reporting it. Repair is a deliberate act (`gate` re-runs the measurement,
    `build-originals --force` re-issues the template), never a side effect of a preview
    render.

    `rewritten` is the set of BASENAMES the caller regenerated. Raises RuntimeError.
    """
    if not recorded:
        return
    stale, gone = [], []
    for fn, want in recorded.items():
        if fn in rewritten:
            continue
        fp = os.path.join(d, fn)
        if not os.path.exists(fp):
            gone.append(fn)
        elif _sha256(fp) != want:
            stale.append(fn)
    if stale or gone:
        bad = sorted(set(stale) | set(gone))
        repair = 're-run the gates (`gate <name>`)' if ANTHRO_REPORT_FILE in bad else 're-render (`refresh-previews`)'
        raise RuntimeError(
            'REFUSING to re-record aux hashes: `%s` does not regenerate %s, and %s no '
            'longer matches what was recorded at issue. Re-recording would clear the '
            'immutability alarm for a file nothing checked. The entry is left exactly as '
            'it was; `verify` will keep reporting it. Repair deliberately: %s to '
            'regenerate the affected file, or `build-originals --force` to re-issue the '
            'template.'
            % (
                what,
                ', '.join(bad),
                ', '.join(['%s: MODIFIED' % f for f in sorted(stale)] + ['%s: MISSING' % f for f in sorted(gone)]),
                repair,
            )
        )
