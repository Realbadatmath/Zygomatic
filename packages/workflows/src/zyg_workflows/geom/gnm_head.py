# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""gnm_head.py — Google GNM Head (Apache-2.0) as the geom stack's scan-grade head.

RUN:
    /usr/bin/python3.12 -m zyg_workflows.geom.gnm_head smoke
    /usr/bin/python3.12 -m zyg_workflows.geom.gnm_head build [--out DIR] [--ids 4] [--seed 7]
                                               [--views 8] [--no-render]

WHY THIS MODULE EXISTS. anny's head is MakeHuman-derived morph space; GNM Head
(github.com/google/GNM, adopted per the 2026-08-09 stack audit) is a statistical
model built from ~5,000 scan subjects: 253 identity components (170 head + 3
eyeball + 80 teeth), 383 expression blendshapes (100 per eye + 150 lower face +
32 tongue + 1 iris), posable neck/head/eye joints, and — unlike every prior open
head model — internal anatomy (eyeballs, teeth, tongue) in ONE parameter space,
under a licence that ships (Apache-2.0, LICENSE verified in-clone). Google's
roadmap adds a body in the same ecosystem; adopting the head now positions the
registry for that drop.

SCOPE, STATED HONESTLY. This is a STANDALONE head system: load, sample, express,
pose, export GLB, render turntable previews, expose the 68-point barycentric
landmark anchors and a differentiable torch handle for future fitting. The
head-to-anny NECK-SEAM BRIDGE — replacing a registered body's head with a GNM
head — is deliberately NOT here; it is the known integration cost that deferred
adoption in the first place and it deserves its own measured build. Nothing in
this module touches mesh_skeletons registry state.

SEMANTIC SAMPLING IS DELIBERATELY ABSENT. GNM's gender/ethnicity/expression
samplers are tiny Keras .h5 decoders and need tensorflow — which is exactly the
dependency this install refused to let pip drag into the shared 3.12 user-site
next to torch cu130 (the SeedVR2-era rule: one leaf at a time, never a framework).
Identity sampling here is clipped N(0,1) in the PCA space instead, which is what
the documented [-3, 3] coefficient range means statistically. If a TF-carrying
venv ever wants the semantic samplers, the guarded import in
``semantic_samplers()`` will find them.

INSTALL FACTS (2026-08-09). Repo: $ZYG_MODELS_ROOT/gnm (shallow clone,
override with ZYG_GNM_REPO). Package: gnm-shape 3.0.0, editable, installed
--no-deps; only new leaves were etils 1.14.0 + typeguard 4.6.0; numpy 2.3.5 and
torch 2.11.0+cu130 byte-identical before/after (guard-asserted). Model data:
gnm/shape/data/versions/v3_0/gnm_head.npz (51 MB, in-repo — no download step).
17,821 vertices / 35,324 triangles / 17,662 quads. Joints: neck, head, left_eye,
right_eye.

Blender preview rendering follows the mv_render pattern: this file is ALSO the
Blender script (blender -b -noaudio --python geom/gnm_head.py -- <config.json>);
detection is "bpy imports". The glTF importer's Y-up -> Z-up conversion is left
to Blender, matching the convention notes in geom/mv_render.py.

Failure semantics match the house judges: the optional VLM face check SKIPS when
the judge is unavailable (recorded, never fabricated); a NO is a real finding;
it flags, it never blocks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time

# ── Blender-mode detection (mv_render pattern) ───────────────────────────────
try:  # pragma: no cover - only true inside Blender
    import bpy  # type: ignore

    _IN_BLENDER = True
except ImportError:
    _IN_BLENDER = False
import logging as _zyg_logging
from zyg_workflows import paths
from zyg_workflows.bin import exe

_zyg_log = _zyg_logging.getLogger(__name__)


GNM_REPO = paths.ZYG_GNM_REPO
BLENDER = os.environ.get('ZYG_BLENDER', str(paths.BLENDER_BIN))

_HERE = os.path.dirname(os.path.abspath(__file__))
_CREWS = os.path.dirname(_HERE)
DEFAULT_OUT = os.path.join(_CREWS, 'data', 'assets', 'gnm_head')

# The documented coefficient range for both parameter spaces.
COEFF_CLIP = 3.0

_CACHE: dict = {}


# ── model loading ────────────────────────────────────────────────────────────


def load_head():
    """The cached numpy-backend GNM Head. Raises ImportError with a pointed
    message if gnm-shape is not installed (install facts in the module header)."""
    if 'head' in _CACHE:
        return _CACHE['head']
    try:
        from gnm.shape import gnm_numpy
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            f'gnm-shape not importable — install per geom/gnm_head.py header (repo expected at {GNM_REPO})'
        ) from exc
    g = gnm_numpy.GNM.from_local(
        version=gnm_numpy.GNMMajorVersion.V3,
        variant=gnm_numpy.GNMVariant.HEAD,
    )
    _CACHE['head'] = g
    return g


def torch_head():
    """Differentiable torch-backend twin of the cached model (float32).
    This is the future fitting hook: identity/expression tensors with
    requires_grad flow through to vertices."""
    if 'torch_head' in _CACHE:
        return _CACHE['torch_head']
    from gnm.shape import gnm_pytorch

    gt = gnm_pytorch.GNM.from_gnm(load_head())
    _CACHE['torch_head'] = gt
    return gt


def landmarks_68():
    """(indices [68,3], weights [68,3]) barycentric anchors on the GNM mesh."""
    if 'lm68' in _CACHE:
        return _CACHE['lm68']
    from gnm.shape import gnm_landmarks

    cfg = gnm_landmarks.load_landmarks(gnm_landmarks.GNMLandmarksType.HEAD_SPARSE_68)
    _CACHE['lm68'] = (cfg.indices, cfg.weights)
    return _CACHE['lm68']


def landmark_points(vertices):
    """68 x 3 landmark positions for a vertex array via barycentric blend."""
    import numpy as np

    idx, w = landmarks_68()
    return (np.asarray(vertices)[idx] * np.asarray(w)[..., None]).sum(axis=1)


def semantic_samplers():
    """(identity_sampler, expression_sampler) or None — the samplers need the
    Keras .h5 decoders and therefore tensorflow, which is deliberately NOT in
    the shared site. Guarded so a TF-carrying venv gets them for free."""
    try:
        from gnm.shape import semantic_sampler  # noqa: F401

        return (semantic_sampler.IdentitySampler(), semantic_sampler.ExpressionSampler())
    except Exception:
        return None


# ── parameter + mesh helpers ─────────────────────────────────────────────────


def neutral_params():
    import numpy as np

    g = load_head()
    return {
        'identity': np.zeros(g.identity_dim, dtype='float32'),
        'expression': np.zeros(g.expression_dim, dtype='float32'),
        'rotations': np.zeros((g.num_joints, 3), dtype='float32'),
        'translation': np.zeros(3, dtype='float32'),
    }


def sample_identity(seed, scale=1.0, clip=COEFF_CLIP):
    """Clipped N(0,1)*scale in the identity PCA space — the statistically
    honest sampler available without tensorflow (see module header)."""
    import numpy as np

    g = load_head()
    rng = np.random.default_rng(int(seed))
    return np.clip(rng.standard_normal(g.identity_dim) * float(scale), -float(clip), float(clip)).astype('float32')


def vertices_for(params):
    g = load_head()
    return g(params['identity'], params['expression'], params['rotations'], params['translation'])


def to_trimesh(vertices):
    import trimesh

    g = load_head()
    return trimesh.Trimesh(vertices=vertices, faces=g.triangles, process=False)


def export_glb(path, vertices):
    """GLB in metres, Y-up (GNM native — Blender's glTF importer converts)."""
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    to_trimesh(vertices).export(path)
    return path


def _sha256(path, cap_mb=512):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 22), b''):
            h.update(block)
    return h.hexdigest()


# ── build: GLBs + manifest + optional renders + optional VLM check ───────────


def build(out_dir=DEFAULT_OUT, n_ids=4, seed=7, views=8, render=True, log=print):
    """Export neutral + sampled heads (+ one expression variant each) as GLBs,
    write a provenance manifest, optionally render turntables + VLM-check them.
    Returns the manifest dict."""
    import numpy as np

    g = load_head()
    t0 = time.time()
    os.makedirs(out_dir, exist_ok=True)

    heads = []
    p = neutral_params()
    heads.append(('neutral', p, vertices_for(p)))
    for k in range(int(n_ids)):
        ident = sample_identity(seed + k)
        pk = neutral_params()
        pk['identity'] = ident
        heads.append((f'id{seed + k:03d}', pk, vertices_for(pk)))

    # one non-neutral expression on the first sampled head: open-mouth-ish push
    # on the lower-face block (components 200:230 of the 383), documented range.
    if int(n_ids) > 0:
        name, pk, _v = heads[1]
        pe = {**pk, 'expression': pk['expression'].copy()}
        pe['expression'][200:230] = 1.5
        heads.append((name + '_expr', pe, vertices_for(pe)))

    npz = os.path.join(GNM_REPO, 'gnm', 'shape', 'data', 'versions', 'v3_0', 'gnm_head.npz')
    try:
        commit = subprocess.run(
            [exe('git'), '-C', GNM_REPO, 'rev-parse', 'HEAD'], capture_output=True, text=True, timeout=20
        ).stdout.strip()
    except Exception:
        commit = ''

    manifest = {
        'model': 'GNM Head v3.0 (google/GNM)',
        'licence': 'Apache-2.0',
        'licence_source': os.path.join(GNM_REPO, 'LICENSE'),
        'repo': GNM_REPO,
        'commit': commit,
        'npz': npz,
        'npz_sha256': _sha256(npz) if os.path.isfile(npz) else None,
        'num_vertices': int(g.num_vertices),
        'num_triangles': int(len(g.triangles)),
        'identity_dim': int(g.identity_dim),
        'expression_dim': int(g.expression_dim),
        'joints': list(getattr(g, 'joint_names', [])),
        'sampling': 'clipped N(0,1) in PCA space (semantic samplers need TF; absent by design)',
        'heads': [],
        'renders': {},
        'vlm_check': None,
    }

    for name, params, verts in heads:
        glb = os.path.join(out_dir, f'gnm_{name}.glb')
        export_glb(glb, verts)
        lo, hi = verts.min(0), verts.max(0)
        manifest['heads'].append(
            {
                'name': name,
                'glb': glb,
                'glb_sha256': _sha256(glb),
                'bbox_m': [[float(x) for x in lo], [float(x) for x in hi]],
                'identity_l2': float(np.linalg.norm(params['identity'])),
                'expression_l2': float(np.linalg.norm(params['expression'])),
            }
        )
        log(f'[gnm_head] {name}: {glb} ({verts.shape[0]} verts, height {hi[1] - lo[1]:.3f} m)')

    if render:
        manifest['renders'] = render_turntables([h['glb'] for h in manifest['heads']], out_dir, views=views, log=log)
        manifest['vlm_check'] = vlm_face_check(manifest['renders'], log=log)

    manifest['elapsed_s'] = round(time.time() - t0, 2)
    mpath = os.path.join(out_dir, 'manifest.json')
    with open(mpath, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=1)
    log(f'[gnm_head] manifest -> {mpath}')
    return manifest


# ── Blender turntable rendering (mv_render self-invoking pattern) ────────────


def render_turntables(glbs, out_dir, views=8, size=768, log=print):
    """Render each GLB on an N-step turntable via headless Blender.
    Returns {glb_basename: [png, ...]}. A missing Blender SKIPS (recorded)."""
    if not os.path.isfile(BLENDER):
        log(f'[gnm_head] blender not found at {BLENDER} — renders skipped')
        return {}
    cfg = {'glbs': list(glbs), 'out_dir': out_dir, 'views': int(views), 'size': int(size)}
    cfg_path = os.path.join(out_dir, '_render_cfg.json')
    with open(cfg_path, 'w', encoding='utf-8') as f:
        json.dump(cfg, f)
    cmd = [BLENDER, '-b', '-noaudio', '--python', os.path.abspath(__file__), '--', cfg_path]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if r.returncode != 0:
        log(f'[gnm_head] blender render FAILED rc={r.returncode}: {(r.stderr or r.stdout)[-400:]}')
        return {}
    out = {}
    for glb in glbs:
        base = os.path.splitext(os.path.basename(glb))[0]
        pngs = sorted(
            os.path.join(out_dir, fn)
            for fn in os.listdir(out_dir)
            if fn.startswith(base + '_v') and fn.endswith('.png')
        )
        out[base] = pngs
        log(f'[gnm_head] rendered {base}: {len(pngs)} views')
    return out


def _blender_main(cfg_path):  # pragma: no cover - runs inside Blender only
    import math

    with open(cfg_path, 'r', encoding='utf-8') as f:
        cfg = json.load(f)
    for glb in cfg['glbs']:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        sc = bpy.context.scene
        sc.render.engine = 'BLENDER_EEVEE_NEXT'
        sc.render.resolution_x = sc.render.resolution_y = cfg['size']
        sc.render.film_transparent = False
        world = bpy.data.worlds.new('w')
        sc.world = world
        world.use_nodes = True
        bg = world.node_tree.nodes['Background']
        bg.inputs[0].default_value = (0.18, 0.19, 0.21, 1.0)
        bg.inputs[1].default_value = 1.0
        bpy.ops.import_scene.gltf(filepath=glb)
        objs = [o for o in sc.objects if o.type == 'MESH']
        # bbox centre in world space (importer already converted Y-up -> Z-up)
        import mathutils

        pts = [o.matrix_world @ mathutils.Vector(c) for o in objs for c in o.bound_box]
        cx = sum(p.x for p in pts) / len(pts)
        cy = sum(p.y for p in pts) / len(pts)
        cz = sum(p.z for p in pts) / len(pts)
        span = max(max(p.z for p in pts) - min(p.z for p in pts), 1e-3)
        dist = span * 2.6
        # neutral grey clay material so identity reads as SHAPE, not shading
        mat = bpy.data.materials.new('clay')
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes['Principled BSDF']
        bsdf.inputs['Base Color'].default_value = (0.63, 0.60, 0.57, 1.0)
        bsdf.inputs['Roughness'].default_value = 0.6
        for o in objs:
            o.data.materials.clear()
            o.data.materials.append(mat)
        cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam'))
        cam.data.lens = 85
        sc.collection.objects.link(cam)
        sc.camera = cam
        key = bpy.data.objects.new('key', bpy.data.lights.new('key', 'AREA'))
        key.data.energy = 120.0
        key.data.size = 1.2
        key.location = (cx + 0.7, cy - 0.9, cz + 0.7)
        sc.collection.objects.link(key)
        base = os.path.splitext(os.path.basename(glb))[0]
        for v in range(cfg['views']):
            az = 2 * math.pi * v / cfg['views']
            cam.location = (cx + dist * math.sin(az), cy - dist * math.cos(az), cz + span * 0.12)
            look = mathutils.Vector((cx, cy, cz)) - cam.location
            cam.rotation_euler = look.to_track_quat('-Z', 'Y').to_euler()
            sc.render.filepath = os.path.join(cfg['out_dir'], f'{base}_v{v:02d}.png')
            bpy.ops.render.render(write_still=True)


# ── optional VLM face check (house failure semantics: skip, never fabricate) ─


def vlm_face_check(renders, max_imgs=3, log=print):
    """Ask the resident judge whether frontal renders show a human head.
    Reject-only second opinion: flags, never blocks; unavailable => skipped."""
    imgs = []
    for _base, pngs in sorted(renders.items()):
        if pngs:
            imgs.append(pngs[0])  # v00 is the frontal view
        if len(imgs) >= max_imgs:
            break
    if not imgs:
        return {'status': 'skipped', 'reason': 'no renders'}
    try:
        sys.path.insert(0, _CREWS)
        from zyg_workflows import vlm_inspector as V

        if not (V.available() and V._enabled()):
            log('[gnm_head] vlm judge unavailable — check skipped, nothing fabricated')
            return {'status': 'skipped', 'reason': 'judge unavailable'}
        # Same worker mechanism region_vlm.judge_cell uses — one closed question.
        q = [
            {
                'id': 'gnm_head_reads',
                'question': 'Does this image show a 3D rendered human head (a grey '
                'clay-like bust)? Judge the anatomy, not the style.',
                'expected': 'yes',
                'severity': 'major',
                'grounding': False,
            }
        ]
        results = []
        for p in imgs:
            res = V._run_worker(V.model_for('resident'), [p], q, 'resident', lambda m: None)
            verd = (res or {}).get('verdicts') or (res or {}).get('answers') or []
            ans = str(verd[0].get('answer', '')).strip().lower() if verd else ''
            verdict = 'skipped' if not res else 'pass' if ans.startswith('y') else 'fail'
            results.append({'image': os.path.basename(p), 'verdict': verdict, 'answer': ans[:60]})
            log(f'[gnm_head] vlm: {os.path.basename(p)} -> {verdict} ({ans[:40]})')
        try:
            V.shutdown_workers()
        except Exception as _exc:
            _zyg_log.warning('vlm worker shutdown failed, judge vram may stay held: %s', _exc)
        return {'status': 'ok', 'results': results}
    except Exception as exc:
        log(f'[gnm_head] vlm check skipped ({type(exc).__name__}: {exc})')
        return {'status': 'skipped', 'reason': f'{type(exc).__name__}: {exc}'}


# ── smoke (the on-interpreter test; .venv-test has no numpy by design) ───────


def _require(cond: object, msg: str) -> None:
    """Raise :class:`RuntimeError` when *cond* is falsy — an ``assert`` that survives ``-O``."""
    if not cond:
        raise RuntimeError(msg)


def smoke(log=print):
    import numpy as np

    g = load_head()
    _require(g.num_vertices == 17821 and len(g.triangles) == 35324, 'topology changed')
    _require(g.identity_dim == 253 and g.expression_dim == 383, 'param dims changed')
    p = neutral_params()
    v0 = vertices_for(p)
    _require(np.isfinite(v0).all(), 'non-finite vertices')
    height = float(v0[:, 1].max() - v0[:, 1].min())
    _require(0.15 < height < 0.6, f'implausible head height {height} m')
    e = p['expression'].copy()
    e[0] = 2.0
    d = float(np.abs(vertices_for({**p, 'expression': e}) - v0).max())
    _require(d > 1e-4, 'expression does not move vertices')
    lm = landmark_points(v0)
    _require(lm.shape == (68, 3) and np.isfinite(lm).all(), 'landmarks broken')
    inside = ((lm >= v0.min(0) - 1e-3) & (lm <= v0.max(0) + 1e-3)).all()
    _require(inside, 'landmarks outside mesh bbox')
    log(
        f'[gnm_head] SMOKE PASS — {g.num_vertices} verts, head height '
        f'{height:.3f} m, 68 landmarks in-bbox, expr delta {d:.5f}'
    )
    return True


# ── CLI ──────────────────────────────────────────────────────────────────────


def _cli():
    ap = argparse.ArgumentParser(description='GNM Head builder (geom stack)')
    sub = ap.add_subparsers(dest='cmd')
    b = sub.add_parser('build', help='export GLBs + manifest + renders')
    b.add_argument('--out', default=DEFAULT_OUT)
    b.add_argument('--ids', type=int, default=4)
    b.add_argument('--seed', type=int, default=7)
    b.add_argument('--views', type=int, default=8)
    b.add_argument('--no-render', action='store_true')
    sub.add_parser('smoke', help='load + invariants, no writes')
    args = ap.parse_args()
    if args.cmd == 'smoke':
        return 0 if smoke() else 1
    if args.cmd == 'build':
        build(out_dir=args.out, n_ids=args.ids, seed=args.seed, views=args.views, render=not args.no_render)
        return 0
    ap.print_help()
    return 0


if _IN_BLENDER:  # pragma: no cover
    _blender_main(sys.argv[sys.argv.index('--') + 1])
elif __name__ == '__main__':
    raise SystemExit(_cli())
