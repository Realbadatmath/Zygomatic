"""ict_face.py — ICT FaceKit LIGHT as the geom stack's ARKit-named expression space.

RUN:
    /usr/bin/python3.12 -m zyg_workflows.geom.ict_face build     # OBJ corpus -> one npz + provenance
    /usr/bin/python3.12 -m zyg_workflows.geom.ict_face smoke     # load + invariants, no writes

WHY THIS MODULE EXISTS. GNM Head gives us 383 expression blendshapes in an
unnamed PCA-ish space; MediaPipe's Face Landmarker emits 52 ARKit-NAMED
blendshape scores per frame. There is no published map between the two, so
driving GNM expression from a video needs a fitter we do not have. ICT FaceKit
Light closes that gap with no fitter at all: its 53 expression morph targets
carry the ARKit names themselves (`jawOpen`, `mouthSmile_L`, ...), so a
MediaPipe score IS the blendshape weight. Identity is a separate 100-mode PCA
over light-stage scans on the same 26,719-vertex topology.

LICENCE (checked at FILE level 2026-09-02, README rule 8). Repo
github.com/ICT-VGL/ICT-FaceKit, LICENSE at the clone root is plain MIT,
"Copyright (c) 2020 USC Institute for Creative Technologies", no use
restriction, no territory clause, no non-commercial clause. The clone contains
the LIGHT model only (`FaceXModel/`: generic_neutral_mesh.obj, identity000-099,
53 named expression OBJs, vertex_indices.json). README line 188 states the FULL
model "will be released under a different USC specific license" and is NOT in
this repo — nothing under a USC-specific licence is fetched, loaded or cached
here. Provenance and the licence quote are written to
data/assets/ict_facekit/PROVENANCE.json by `build()`.

WHAT IS BUILT. The shipped Scripts/ict_face_model.py needs `openmesh`, which is
not installed on 3.12 and is not worth a build-from-source for a static morph
corpus. `build()` parses the OBJs with a numpy fast path and writes ONE
float32 npz (data/assets/ict_facekit/ict_light_v1.npz, ~49 MB):

    neutral      [26719, 3]        generic_neutral_mesh
    id_modes     [100, 26719, 3]   identityNNN - neutral
    ex_modes     [53, 26719, 3]    <expr> - neutral
    faces        [F, 3]            triangulated from the quads/ngons in the OBJ
    landmarks68  [68]              vertex indices, ICT's own idx_to_landmark_verts

`model()` returns that as a cached dict; `deform(id_w, ex_w)` is the linear
forward. UNITS ARE CENTIMETRES, measured on the neutral mesh, not assumed: its
bbox spans 24.83 x 33.81 x 22.32, which is a head in cm and nothing else.
`MODEL_UNITS_PER_M = 100.0` is the one place that conversion lives. Identity weights are the OBJ corpus's own PCA coefficients: the shipped
convention (Scripts/ict_face_model.py:199) is a PLAIN linear blend of the
difference modes, so weight 1.0 means "one whole identity000 mode away from
neutral", NOT one standard deviation. Nothing here pretends otherwise.

BLENDSHAPE NAMES. `mp_to_ict()` maps MediaPipe's 52 to ICT's 53 by name, and
the difference is exactly two splits: ARKit's single `browInnerUp` and
`cheekPuff` are per-side in ICT, so one score drives both sides. MediaPipe's
`_neutral` is a confidence channel, not a shape, and is dropped. The map is
DERIVED from the two name lists at import time and asserted complete — a
silently half-connected rig is the failure mode this module exists to avoid.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from zyg_workflows import paths
from zyg_workflows.bin import exe

ICT_REPO = paths.ZYG_ICT_REPO
FACEX = os.path.join(ICT_REPO, 'FaceXModel')

_HERE = os.path.dirname(os.path.abspath(__file__))
_CREWS = os.path.dirname(_HERE)
ASSET_DIR = os.path.join(_CREWS, 'data', 'assets', 'ict_facekit')
NPZ = os.path.join(ASSET_DIR, 'ict_light_v1.npz')

N_VERTS = 26719
N_ID = 100
N_EX = 53

# Measured on generic_neutral_mesh.obj (bbox 24.83 x 33.81 x 22.32): the corpus
# is in centimetres. Every metric this stack reports is in mm or m, so anything
# leaving ict_face divides by this.
MODEL_UNITS_PER_M = 100.0

_CACHE: dict = {}


# ── MediaPipe 52 (ARKit) ─────────────────────────────────────────────────────
# The Face Landmarker's category_name roster, in its emitted order. Index 0 is
# `_neutral`, a confidence channel rather than a morph target.
MP_BLENDSHAPES = [
    '_neutral',
    'browDownLeft',
    'browDownRight',
    'browInnerUp',
    'browOuterUpLeft',
    'browOuterUpRight',
    'cheekPuff',
    'cheekSquintLeft',
    'cheekSquintRight',
    'eyeBlinkLeft',
    'eyeBlinkRight',
    'eyeLookDownLeft',
    'eyeLookDownRight',
    'eyeLookInLeft',
    'eyeLookInRight',
    'eyeLookOutLeft',
    'eyeLookOutRight',
    'eyeLookUpLeft',
    'eyeLookUpRight',
    'eyeSquintLeft',
    'eyeSquintRight',
    'eyeWideLeft',
    'eyeWideRight',
    'jawForward',
    'jawLeft',
    'jawOpen',
    'jawRight',
    'mouthClose',
    'mouthDimpleLeft',
    'mouthDimpleRight',
    'mouthFrownLeft',
    'mouthFrownRight',
    'mouthFunnel',
    'mouthLeft',
    'mouthLowerDownLeft',
    'mouthLowerDownRight',
    'mouthPressLeft',
    'mouthPressRight',
    'mouthPucker',
    'mouthRight',
    'mouthRollLower',
    'mouthRollUpper',
    'mouthShrugLower',
    'mouthShrugUpper',
    'mouthSmileLeft',
    'mouthSmileRight',
    'mouthStretchLeft',
    'mouthStretchRight',
    'mouthUpperUpLeft',
    'mouthUpperUpRight',
    'noseSneerLeft',
    'noseSneerRight',
]


def ict_expression_names():
    """ICT's own 53 expression names, from vertex_indices.json (not hardcoded)."""
    if 'ex_names' in _CACHE:
        return _CACHE['ex_names']
    with open(os.path.join(FACEX, 'vertex_indices.json'), encoding='utf-8') as f:
        d = json.load(f)
    names = [str(n) for n in d['expressions']]
    _CACHE['ex_names'] = names
    _CACHE['lm68_idx'] = [int(i) for i in d['idx_to_landmark_verts']]
    return names


def mp_to_ict():
    """{mediapipe_name: [ict_index, ...]} — derived from the two rosters, never
    hand-typed. `browInnerUp` and `cheekPuff` are one ARKit channel and two ICT
    targets, so they map to a pair; `_neutral` maps to nothing (it is a
    confidence, not a shape). Raises if any ICT target is left unconnected."""
    if 'mp2ict' in _CACHE:
        return _CACHE['mp2ict']
    names = ict_expression_names()
    pos = {n: i for i, n in enumerate(names)}
    out = {}
    for mp in MP_BLENDSHAPES:
        if mp == '_neutral':
            out[mp] = []
            continue
        if mp in pos:  # same name both sides of the map
            cand = [mp]  #   (jawLeft, mouthRight, jawOpen...)
        elif mp.endswith('Left'):
            cand = [mp[:-4] + '_L']
        elif mp.endswith('Right'):
            cand = [mp[:-5] + '_R']
        elif mp + '_L' in pos:  # ARKit single, ICT per-side
            cand = [mp + '_L', mp + '_R']
        else:
            cand = [mp]
        idx = [pos[c] for c in cand if c in pos]
        if not idx:
            raise RuntimeError(f'MediaPipe blendshape {mp!r} has no ICT target (tried {cand}) — mapping is incomplete')
        out[mp] = idx
    hit = {i for v in out.values() for i in v}
    missing = [names[i] for i in range(len(names)) if i not in hit]
    if missing:
        raise RuntimeError(f'ICT targets no MediaPipe channel reaches: {missing}')
    _CACHE['mp2ict'] = out
    return out


def ex_weights_from_blendshapes(scores):
    """{mp_name: score} -> ICT expression weight vector [53], clipped to [0,1].
    Unknown keys are ignored; absent channels stay 0. A split channel
    (browInnerUp, cheekPuff) writes the same score to both sides."""
    import numpy as np

    w = np.zeros(N_EX, dtype='float32')
    m = mp_to_ict()
    for name, s in (scores or {}).items():
        for i in m.get(name, ()):
            w[i] = float(np.clip(s, 0.0, 1.0))
    return w


# ── OBJ parsing ──────────────────────────────────────────────────────────────


def _read_obj(path, want_faces=False):
    """(vertices [V,3] float32, faces [F,3] int32 or None). Fast enough on a
    2.5 MB ASCII OBJ (~0.1 s) without dragging in a mesh library: ICT's OBJs are
    plain `v`/`vt`/`vn`/`f` with no groups that matter to a morph corpus."""
    import numpy as np

    vs = []
    fs = []
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            if line.startswith('v '):
                p = line.split()
                vs.append((float(p[1]), float(p[2]), float(p[3])))
            elif want_faces and line.startswith('f '):
                idx = [int(t.split('/')[0]) - 1 for t in line.split()[1:]]
                for k in range(1, len(idx) - 1):  # fan-triangulate quads/ngons
                    fs.append((idx[0], idx[k], idx[k + 1]))
    v = np.asarray(vs, dtype='float32')
    return v, (np.asarray(fs, dtype='int32') if want_faces else None)


def _sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 22), b''):
            h.update(block)
    return h.hexdigest()


# ── build ────────────────────────────────────────────────────────────────────


def build(out_npz=NPZ, log=print):
    """Parse the FaceXModel OBJ corpus into one npz + PROVENANCE.json."""
    import numpy as np

    t0 = time.time()
    os.makedirs(ASSET_DIR, exist_ok=True)
    neutral, faces = _read_obj(os.path.join(FACEX, 'generic_neutral_mesh.obj'), want_faces=True)
    if neutral.shape != (N_VERTS, 3):
        raise RuntimeError(
            f'neutral mesh is {neutral.shape}, expected {(N_VERTS, 3)} — this is not the ICT LIGHT topology'
        )
    log(f'[ict_face] neutral {neutral.shape[0]} verts, {faces.shape[0]} tris')

    id_modes = np.zeros((N_ID, N_VERTS, 3), dtype='float32')
    for i in range(N_ID):
        v, _ = _read_obj(os.path.join(FACEX, f'identity{i:03d}.obj'))
        id_modes[i] = v - neutral
        if i % 25 == 0:
            log(f'[ict_face] identity {i:03d}/{N_ID}  |delta|max {np.abs(id_modes[i]).max():.4f}')

    names = ict_expression_names()
    ex_modes = np.zeros((N_EX, N_VERTS, 3), dtype='float32')
    for i, nm in enumerate(names):
        v, _ = _read_obj(os.path.join(FACEX, f'{nm}.obj'))
        ex_modes[i] = v - neutral
    log(
        f'[ict_face] {N_EX} expression modes, largest single-vertex travel '
        f'{np.linalg.norm(ex_modes, axis=2).max():.4f} model units'
    )

    ict_expression_names()  # populates lm68_idx
    lm68 = np.asarray(_CACHE['lm68_idx'], dtype='int32')

    np.savez_compressed(
        out_npz,
        neutral=neutral,
        id_modes=id_modes,
        ex_modes=ex_modes,
        faces=faces,
        landmarks68=lm68,
        expression_names=np.array(names),
    )
    log(f'[ict_face] npz -> {out_npz} ({os.path.getsize(out_npz) / 1e6:.1f} MB, {time.time() - t0:.1f}s)')

    try:
        commit = subprocess.run(
            [exe('git'), '-C', ICT_REPO, 'rev-parse', 'HEAD'], capture_output=True, text=True, timeout=20
        ).stdout.strip()
    except Exception:
        commit = ''
    with open(os.path.join(ICT_REPO, 'LICENSE'), encoding='utf-8') as f:
        licence_text = f.read()
    prov = {
        'model': 'ICT FaceKit — ICT Face Model LIGHT',
        'variant': 'light',
        'repo_url': 'https://github.com/ICT-VGL/ICT-FaceKit',
        'clone': ICT_REPO,
        'commit': commit,
        'licence': 'MIT',
        'licence_file': os.path.join(ICT_REPO, 'LICENSE'),
        'licence_quote': licence_text.strip().splitlines()[0] + ' — ' + licence_text.strip().splitlines()[2],
        'licence_full': licence_text,
        'licence_checked': '2026-09-02',
        'licence_check_notes': 'File-level check per session README rule 8: LICENSE is plain MIT '
        '(c) 2020 USC Institute for Creative Technologies. No non-commercial '
        'clause, no territory clause, no output restriction. Weights and code '
        'are the same MIT grant here — the shape modes ARE the repo content. '
        'The FULL ICT model is NOT in this clone (README:188 says it will be '
        'released under a different USC-specific licence) and is not fetched.',
        'topology': {
            'vertices': int(N_VERTS),
            'triangles': int(faces.shape[0]),
            'identity_modes': N_ID,
            'expression_modes': N_EX,
        },
        'expression_names': names,
        'npz': out_npz,
        'npz_sha256': _sha256(out_npz),
        'neutral_obj_sha256': _sha256(os.path.join(FACEX, 'generic_neutral_mesh.obj')),
        'vertex_indices_sha256': _sha256(os.path.join(FACEX, 'vertex_indices.json')),
        'identity_weight_semantics': 'plain linear blend of (identityNNN - neutral); weight 1.0 = one whole '
        'shipped mode, NOT one standard deviation (Scripts/ict_face_model.py:199)',
        'built': time.strftime('%Y-%m-%dT%H:%M:%S'),
    }
    ppath = os.path.join(ASSET_DIR, 'PROVENANCE.json')
    with open(ppath, 'w', encoding='utf-8') as f:
        json.dump(prov, f, indent=1)
    log(f'[ict_face] provenance -> {ppath}')
    return prov


# ── model access ─────────────────────────────────────────────────────────────


def model():
    """Cached dict: neutral, id_modes, ex_modes, faces, landmarks68, ex_names."""
    if 'model' in _CACHE:
        return _CACHE['model']
    import numpy as np

    if not os.path.isfile(NPZ):
        raise FileNotFoundError(f'{NPZ} missing — run: /usr/bin/python3.12 -m zyg_workflows.geom.ict_face build')
    z = np.load(NPZ, allow_pickle=False)
    m = {
        'neutral': z['neutral'],
        'id_modes': z['id_modes'],
        'ex_modes': z['ex_modes'],
        'faces': z['faces'],
        'landmarks68': z['landmarks68'],
        'ex_names': [str(n) for n in z['expression_names']],
    }
    _CACHE['model'] = m
    return m


def deform(id_w=None, ex_w=None):
    """Vertices [26719,3] for identity weights [100] and expression weights [53].
    Both default to zero (the generic neutral mesh)."""
    import numpy as np

    m = model()
    v = m['neutral'].astype('float32').copy()
    if id_w is not None:
        v += np.tensordot(np.asarray(id_w, dtype='float32'), m['id_modes'], axes=(0, 0))
    if ex_w is not None:
        v += np.tensordot(np.asarray(ex_w, dtype='float32'), m['ex_modes'], axes=(0, 0))
    return v


def landmark_points(vertices):
    """68 x 3 landmark positions — ICT's own vertex picks, same iBUG-68 ordering
    the GNM sparse-68 set uses."""
    import numpy as np

    return np.asarray(vertices)[model()['landmarks68']]


# ── smoke ────────────────────────────────────────────────────────────────────


def _require(cond: object, msg: str) -> None:
    """Raise :class:`RuntimeError` when *cond* is falsy — an ``assert`` that survives ``-O``."""
    if not cond:
        raise RuntimeError(msg)


def smoke(log=print):
    import numpy as np

    m = model()
    _require(m['neutral'].shape == (N_VERTS, 3), 'topology changed')
    _require(m['id_modes'].shape == (N_ID, N_VERTS, 3), 'identity modes changed')
    _require(m['ex_modes'].shape == (N_EX, N_VERTS, 3), 'expression modes changed')
    mp = mp_to_ict()
    _require(len(mp) == 52 and mp['_neutral'] == [], 'MediaPipe roster changed')
    _require(len(mp['browInnerUp']) == 2 and len(mp['cheekPuff']) == 2, 'splits lost')
    hit = {i for v in mp.values() for i in v}
    _require(len(hit) == N_EX, f'only {len(hit)}/{N_EX} ICT targets reachable')
    w = ex_weights_from_blendshapes({'jawOpen': 1.0, 'browInnerUp': 0.5})
    j = m['ex_names'].index('jawOpen')
    _require(w[j] == 1.0 and w[m['ex_names'].index('browInnerUp_R')] == 0.5, 'map broken')
    v0 = deform()
    v1 = deform(ex_w=w)
    travel = float(np.abs(v1 - v0).max())
    _require(travel > 1e-4, 'jawOpen does not move vertices')
    lm = landmark_points(v0)
    _require(lm.shape == (68, 3) and np.isfinite(lm).all(), 'landmarks broken')
    span = float(v0[:, 1].max() - v0[:, 1].min())
    log(
        f'[ict_face] SMOKE PASS — {N_VERTS} verts, {N_ID} id / {N_EX} expr modes, '
        f'52->53 map complete, jawOpen travel {travel:.4f}, head span {span:.3f} '
        f'model units, 68 landmarks finite'
    )
    return True


def _cli():
    ap = argparse.ArgumentParser(description='ICT FaceKit Light (geom stack)')
    sub = ap.add_subparsers(dest='cmd')
    b = sub.add_parser('build')
    b.add_argument('--out', default=NPZ)
    sub.add_parser('smoke')
    args = ap.parse_args()
    if args.cmd == 'build':
        build(out_npz=args.out)
        return 0
    if args.cmd == 'smoke':
        return 0 if smoke() else 1
    ap.print_help()
    return 0


if __name__ == '__main__':
    raise SystemExit(_cli())
