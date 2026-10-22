# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""prop_mesh_library.py — the registered library of BUILT geometry (props + creatures).

WHY THIS EXISTS.
`prop_mesh/*.py` builds real geometry in Blender and drops the result wherever the
caller pointed `--out`. For the Pufferball that was
`lora-datasets/creatures/<id>/mesh/` — a LoRA *working* tree, which is rebuilt,
re-staged and pruned by the training services. A mesh that took a build script, a
16-view render and 48 EXR passes to produce must not live somewhere a trainer is
entitled to delete, and nothing downstream could address it by name: every consumer
would have had to hard-code a dataset path.

This module is the other half — the ASSET side. It owns one canonical tree,

    data/assets/prop_meshes/<asset_id>/

records each asset in `registry.json` with a sha256 per file, and hands consumers
paths BY NAME (`glb_path('pufferball')`, `pass_path('pufferball','top_down','depth')`)
instead of by directory guess. It deliberately mirrors the shape of the
`mesh_skeletons` registry (dir / glb / sha256 / aux_sha256 / previews / params) so the
GUI's Mesh tab can list both from one code path — but it is a SEPARATE registry,
because mesh_skeletons is the human-body cage tree: its records carry anthropometric
gate verdicts and an immutable-original contract that mean nothing for a creature and
would be a lie on its card.

WHAT A RECORD PROMISES, AND WHAT IT DOES NOT.
  * `glb`      the portable master. glTF has NO concept of a Blender particle system,
               so **the fur does not travel in it** — the GLB is the bare body
               surface. This is recorded in the record itself (`geometry.fur`), not
               left for a consumer to discover in a render.
  * `blend`    the editable master, which DOES carry hair, modifiers and materials.
  * `passes/`  per-view depth / normal / IndexOB EXRs. These matter more than the
               beauty renders: a depth pass is a TRUE depth buffer out of the
               renderer, not a Depth-Anything estimate, so conditioning on it costs
               nothing in licence terms (`arcane_restyle` has to refuse
               Depth-Anything's vitb/vitl/vitg checkpoints because they are
               CC-BY-NC-4.0). Geometry we built cannot carry someone else's licence.
  * `licence`  every asset states its origin. The channel is monetised, so "where did
               this geometry come from" is a shipping question, not trivia. The
               Pufferball is procedural — built from primitives by a script we wrote —
               which is exactly why it exists: EVERY image->mesh regressor is
               non-commercial (see prop_mesh/pufferball.py's header).

INTEGRITY. `verify()` re-hashes every recorded file. Registration is a COPY, never a
move: the build tree keeps its output, so a failed or half-finished registration can
never destroy the only copy of a mesh.

CLI:
    python3 prop_mesh_library.py --list
    python3 prop_mesh_library.py --verify [asset_id]
    python3 prop_mesh_library.py --show asset_id
"""

import hashlib
import json
import os
import shutil
import threading
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(_HERE, 'data', 'assets', 'prop_meshes')
REGISTRY = os.path.join(ROOT, 'registry.json')
SCHEMA = 1

# Beauty renders and control passes. The pass suffixes are what the Blender
# compositor's file-output slots are named in prop_mesh/*_sheet.py.
_PASS_KINDS = ('depth', 'normal', 'index')
_IMG_EXT = ('.png', '.jpg', '.jpeg', '.webp')
_PASS_EXT = ('.exr',)

_LOCK = threading.Lock()


# ── hashing / registry io ────────────────────────────────────────────────────
def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for block in iter(lambda: fh.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def load_registry():
    """The whole registry, or an empty one. Never raises on a missing/half-written file —
    a mid-rewrite read must not take a GUI tab down with it."""
    try:
        with open(REGISTRY, encoding='utf-8') as fh:
            reg = json.load(fh)
    except (OSError, ValueError):
        return {'schema': SCHEMA, 'assets': {}}
    if not isinstance(reg, dict) or not isinstance(reg.get('assets'), dict):
        return {'schema': SCHEMA, 'assets': {}}
    return reg


def _save_registry(reg):
    os.makedirs(ROOT, exist_ok=True)
    tmp = REGISTRY + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(reg, fh, indent=2, sort_keys=False)
        fh.write('\n')
    os.replace(tmp, REGISTRY)


def list_assets():
    """Records newest-first, each with its own id folded in."""
    reg = load_registry()
    out = []
    for aid, rec in (reg.get('assets') or {}).items():
        rec = dict(rec)
        rec['id'] = aid
        out.append(rec)
    out.sort(key=lambda r: str((r.get('provenance') or {}).get('registered') or ''), reverse=True)
    return out


def get(asset_id):
    rec = (load_registry().get('assets') or {}).get(asset_id)
    if rec is None:
        return None
    rec = dict(rec)
    rec['id'] = asset_id
    return rec


# ── path resolution: consumers ask by NAME, never by directory ───────────────
def asset_dir(asset_id):
    rec = get(asset_id)
    return os.path.join(ROOT, rec['dir']) if rec else None


def _rel(rec, key):
    v = rec.get(key)
    return os.path.join(ROOT, rec['dir'], v) if v else None


def glb_path(asset_id):
    """The portable master. Geometry only — no fur (see module docstring)."""
    rec = get(asset_id)
    return _rel(rec, 'glb') if rec else None


def blend_path(asset_id):
    """The editable master — hair, modifiers and materials included."""
    rec = get(asset_id)
    return _rel(rec, 'blend') if rec else None


def sheet(asset_id):
    """The build manifest (view plan, camera distances, build params, IndexOB map)."""
    rec = get(asset_id)
    p = _rel(rec, 'sheet') if rec else None
    if not p or not os.path.isfile(p):
        return None
    try:
        with open(p, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def view_ids(asset_id):
    rec = get(asset_id)
    return list((rec.get('views') or {}).get('ids') or []) if rec else []


def beauty_path(asset_id, view_id):
    """The shaded render for one view — directly usable as a training tile."""
    d = asset_dir(asset_id)
    if not d:
        return None
    for ext in _IMG_EXT:
        p = os.path.join(d, 'beauty', view_id + ext)
        if os.path.isfile(p):
            return p
    return None


def pass_path(asset_id, view_id, kind='depth'):
    """A control pass for one view. `kind` in ('depth','normal','index').

    THIS is the function the diffusion stack wants: a depth EXR straight out of
    Cycles, so nothing downstream has to run a depth ESTIMATOR over a render and
    inherit that estimator's licence."""
    if kind not in _PASS_KINDS:
        raise ValueError('kind must be one of %s' % (_PASS_KINDS,))
    d = asset_dir(asset_id)
    if not d:
        return None
    pdir = os.path.join(d, 'passes')
    if not os.path.isdir(pdir):
        return None
    stem = '%s_%s_' % (view_id, kind)
    hits = sorted(f for f in os.listdir(pdir) if f.startswith(stem) and f.lower().endswith(_PASS_EXT))
    return os.path.join(pdir, hits[0]) if hits else None


def views(asset_id):
    """[{id, azimuth, elevation, framing, distance_m, beauty, depth, normal, index}]

    One row per rendered viewpoint with every file that exists for it resolved to an
    absolute path (missing ones are None rather than absent, so a caller can see WHICH
    half is missing)."""
    sh = sheet(asset_id) or {}
    rows = []
    for v in sh.get('views') or []:
        vid = v.get('id')
        row = {k: v.get(k) for k in ('id', 'azimuth', 'elevation', 'framing', 'distance_m')}
        row['beauty'] = beauty_path(asset_id, vid)
        for k in _PASS_KINDS:
            row[k] = pass_path(asset_id, vid, k)
        rows.append(row)
    return rows


# ── integrity ────────────────────────────────────────────────────────────────
def verify(asset_id=None):
    """Re-hash every recorded file. -> {asset_id: {'ok': bool, 'bad': [...], 'missing': [...]}}

    Recorded, not present: a file that appeared in the folder after registration is
    not part of the asset and is not checked — the registry is the manifest."""
    reg = load_registry()
    out = {}
    for aid, rec in (reg.get('assets') or {}).items():
        if asset_id and aid != asset_id:
            continue
        d = os.path.join(ROOT, rec.get('dir', ''))
        bad, missing = [], []
        for rel, want in sorted((rec.get('sha256') or {}).items()):
            p = os.path.join(d, rel)
            if not os.path.isfile(p):
                missing.append(rel)
            elif sha256_file(p) != want:
                bad.append(rel)
        out[aid] = {
            'ok': not bad and not missing,
            'bad': bad,
            'missing': missing,
            'files': len(rec.get('sha256') or {}),
        }
    return out


# ── registration ─────────────────────────────────────────────────────────────
def _copy_tree(src, dst, exts=None):
    """Copy one flat directory. Returns the basenames copied, sorted."""
    if not os.path.isdir(src):
        return []
    os.makedirs(dst, exist_ok=True)
    names = []
    for fn in sorted(os.listdir(src)):
        sp = os.path.join(src, fn)
        if not os.path.isfile(sp):
            continue
        if exts and not fn.lower().endswith(tuple(exts)):
            continue
        shutil.copy2(sp, os.path.join(dst, fn))
        names.append(fn)
    return names


FUR_GEOMETRY_TAGS = ('_locks', '_tuft', '_wisp', '_fringe')


def _is_fur_node(name):
    """A GLB node that is fur GEOMETRY (a look layer's lock/tuft/wisp meshes), not
    body. Same tags as pufferball.is_fur_geometry — keep them in step."""
    return any(t in name for t in FUR_GEOMETRY_TAGS)


def _flatten(glb, exclude_fur=False):
    """One mesh in WORLD space.

    `trimesh.util.concatenate(scene.geometry.values())` looks like the obvious way to
    merge a multi-part GLB and is wrong: it takes each part's LOCAL vertices and drops
    the scene-graph transform that places it. On this creature that under-reports the
    bounding box by 30% (0.42 x 0.33 x 0.46 m becomes 0.32 x 0.27 x 0.30) and piles
    every part on the origin. `Scene.to_mesh()` applies the node transforms."""
    import trimesh

    scn = trimesh.load(glb, force='scene')
    if exclude_fur and hasattr(scn, 'geometry'):
        drop = [k for k in scn.geometry if _is_fur_node(k)]
        if drop:
            scn.delete_geometry(drop)
    if hasattr(scn, 'to_mesh'):
        return scn.to_mesh()
    return trimesh.util.concatenate(scn.dump())


def export_mesh3d(glb, out_path, z_up=True):
    """Write the GUI 3D viewer's ZM3D binary from a GLB.

    Same format geom/mesh_skeletons._export_mesh3d writes, so inspection.html's orbit
    viewer loads a creature with no new client code: magic 'ZM3D' + uint32
    version,nv,ntri,nedge + float32 v[nv*3] + uint32 tri[ntri*3] + uint32 edge[nedge*2].

    z_up: glTF is Y-up and the viewer's camera is Z-up (`camera.up.set(0,0,1)`), so the
    vertices are rotated back into Blender's frame — (x, y, z)_gltf -> (x, -z, y). Skip
    it and the creature lies on its side in the viewer.

    The edge list is the mesh's unique triangle edges. For a skeleton, mesh_skeletons
    can supply the TRUE quad cage; a triangulated GLB has no such thing, so the grid
    here is honestly labelled a triangle wireframe rather than pretending to be a cage."""
    import numpy as np

    # The viewer gets the SOLID creature: the canon look's fur geometry is ~300k
    # verts of strands that turn the orbit view into a hairball and the wireframe
    # into noise. Fur is a render-time thing; the viewer shows form.
    mesh = _flatten(glb, exclude_fur=True)
    v = np.asarray(mesh.vertices, dtype=np.float64)
    if z_up:
        v = np.column_stack([v[:, 0], -v[:, 2], v[:, 1]])
    v32 = v.astype(np.float32)
    tris = np.asarray(mesh.faces, dtype=np.uint32)
    e = np.vstack([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    e = np.unique(np.sort(e, axis=1), axis=0).astype(np.uint32)
    head = b'ZM3D' + np.array([1, len(v32), len(tris), len(e)], np.uint32).tobytes()
    tmp = out_path + '.tmp'
    with open(tmp, 'wb') as fh:
        fh.write(head)
        fh.write(v32.tobytes())
        fh.write(tris.tobytes())
        fh.write(e.tobytes())
    os.replace(tmp, out_path)
    return {'vertices': int(len(v32)), 'triangles': int(len(tris)), 'edges': int(len(e))}


def geometry_stats(glb):
    """Per-part and total counts + the real-world bounding box, measured from the GLB.

    Reported in the BLENDER frame (Z up) so the numbers read the way the build script
    and the sheet's `size_m` do."""
    import numpy as np
    import trimesh

    scn = trimesh.load(glb, force='scene')
    geoms = scn.geometry if hasattr(scn, 'geometry') else {'mesh': scn}
    parts = {k: {'vertices': int(len(g.vertices)), 'triangles': int(len(g.faces))} for k, g in geoms.items()}
    merged = _flatten(glb)
    # size_m is the SOLID creature: with the canon look the GLB also carries lock and
    # wisp fur meshes reaching 120 mm past the body, and a bbox over those describes
    # the fur, not the animal (0.70 m wide against a 0.37 m body). The full extent is
    # still reported, as fur_extent_m.
    solid = _flatten(glb, exclude_fur=True)

    def _box(m):
        v = np.asarray(m.vertices)
        lo, hi = v.min(axis=0), v.max(axis=0)
        # glTF Y-up -> Blender Z-up: (x, y, z) -> (x, -z, y)
        return ((float(lo[0]), float(hi[0])), (float(-hi[2]), float(-lo[2])), (float(lo[1]), float(hi[1])))

    bx, by, bz = _box(solid)
    fx, fy, fz = _box(merged)
    fur_nodes = [k for k in parts if _is_fur_node(k)]
    return {
        'vertices': int(len(merged.vertices)),
        'triangles': int(len(merged.faces)),
        'vertices_solid': int(len(solid.vertices)),
        'triangles_solid': int(len(solid.faces)),
        'parts': len(parts),
        'fur_nodes': fur_nodes,
        'fur_extent_m': {
            'width': round(fx[1] - fx[0], 5),
            'depth': round(fy[1] - fy[0], 5),
            'height': round(fz[1] - fz[0], 5),
        }
        if fur_nodes
        else None,
        'part_counts': parts,
        'bbox_m': {
            'x': [round(bx[0], 5), round(bx[1], 5)],
            'y': [round(by[0], 5), round(by[1], 5)],
            'z': [round(bz[0], 5), round(bz[1], 5)],
        },
        'size_m': {
            'width': round(bx[1] - bx[0], 5),
            'depth': round(by[1] - by[0], 5),
            'height': round(bz[1] - bz[0], 5),
        },
        'watertight': bool(merged.is_watertight),
    }


def register(
    asset_id,
    src_dir,
    *,
    name,
    kind='prop',
    glb=None,
    blend=None,
    sheet_name='sheet.json',
    creature_id=None,
    licence=None,
    provenance=None,
    description='',
    tags=(),
    copy_passes=True,
    registered=None,
    replace=False,
):
    """Copy a build output into the library and record it.

    src_dir is a prop_mesh build tree: <glb>, <blend>, sheet.json, beauty/, passes/.
    Returns the stored record. Raises ValueError if the id already exists and
    replace is False — re-registering silently over a shipped asset is how a mesh
    changes underneath a scene that already used it."""
    reg = load_registry()
    assets = reg.setdefault('assets', {})
    reg.setdefault('schema', SCHEMA)
    if asset_id in assets and not replace:
        raise ValueError('%r already registered — pass replace=True to re-issue' % asset_id)
    if not os.path.isdir(src_dir):
        raise ValueError('no such build dir: %s' % src_dir)

    glb = glb or next((f for f in sorted(os.listdir(src_dir)) if f.endswith('.glb')), None)
    if not glb or not os.path.isfile(os.path.join(src_dir, glb)):
        raise ValueError('no .glb in %s' % src_dir)
    blend = blend or next((f for f in sorted(os.listdir(src_dir)) if f.endswith('.blend')), None)

    dst = os.path.join(ROOT, asset_id)
    os.makedirs(dst, exist_ok=True)
    shutil.copy2(os.path.join(src_dir, glb), os.path.join(dst, glb))
    if blend and os.path.isfile(os.path.join(src_dir, blend)):
        shutil.copy2(os.path.join(src_dir, blend), os.path.join(dst, blend))
    else:
        blend = None
    if sheet_name and os.path.isfile(os.path.join(src_dir, sheet_name)):
        shutil.copy2(os.path.join(src_dir, sheet_name), os.path.join(dst, sheet_name))
    else:
        sheet_name = None

    beauty = _copy_tree(os.path.join(src_dir, 'beauty'), os.path.join(dst, 'beauty'), _IMG_EXT)
    passes = _copy_tree(os.path.join(src_dir, 'passes'), os.path.join(dst, 'passes'), _PASS_EXT) if copy_passes else []

    # The sheet's absolute `beauty` paths point back at the BUILD tree; rewrite them to
    # this asset's own files, or every consumer that trusts the sheet silently reads
    # from a directory the trainer may delete.
    if sheet_name:
        sp = os.path.join(dst, sheet_name)
        try:
            with open(sp, encoding='utf-8') as fh:
                sh = json.load(fh)
            sh['out'] = dst
            sh['asset_id'] = asset_id
            for v in sh.get('views') or []:
                b = beauty_path_local(dst, v.get('id'))
                if b:
                    v['beauty'] = b
                for k in _PASS_KINDS:
                    p = pass_path_local(dst, v.get('id'), k)
                    if p:
                        v[k] = p
            with open(sp, 'w', encoding='utf-8') as fh:
                json.dump(sh, fh, indent=2)
                fh.write('\n')
        except (OSError, ValueError) as _exc:
            _zyg_log.warning('sheet %s path rewrite failed, consumers will read the build tree: %s', sheet_name, _exc)

    mesh3d_stats = None
    try:
        mesh3d_stats = export_mesh3d(os.path.join(dst, glb), os.path.join(dst, 'mesh3d.bin'))
    except Exception as exc:  # noqa: BLE001
        mesh3d_stats = {'error': str(exc)}

    hashes = {}
    for rel in (
        [glb]
        + ([blend] if blend else [])
        + ([sheet_name] if sheet_name else [])
        + (['mesh3d.bin'] if os.path.isfile(os.path.join(dst, 'mesh3d.bin')) else [])
    ):
        hashes[rel] = sha256_file(os.path.join(dst, rel))
    for fn in beauty:
        hashes['beauty/' + fn] = sha256_file(os.path.join(dst, 'beauty', fn))
    for fn in passes:
        hashes['passes/' + fn] = sha256_file(os.path.join(dst, 'passes', fn))

    try:
        stats = geometry_stats(os.path.join(dst, glb))
    except Exception as exc:  # noqa: BLE001
        stats = {'error': str(exc)}
    stats['fur'] = (
        'particle hair — lives in the .blend ONLY; glTF has no particle system, so the .glb is the bare body surface'
    )
    if mesh3d_stats:
        stats['mesh3d'] = mesh3d_stats

    ids = []
    try:
        with open(os.path.join(dst, sheet_name), encoding='utf-8') as fh:
            ids = [v.get('id') for v in (json.load(fh).get('views') or [])]
    except Exception:  # noqa: BLE001
        ids = sorted(os.path.splitext(f)[0] for f in beauty)

    # previews follow the SHEET'S ANGLE ORDER, not the directory's alphabetical one.
    # A card shows previews[0]; sorted() makes that 'back.png', so the Pufferball's
    # library card would have led with the back of his head.
    by_stem = {os.path.splitext(f)[0]: f for f in beauty}
    ordered = [by_stem[i] for i in ids if i in by_stem]
    ordered += [f for f in beauty if f not in ordered]

    rec = {
        'name': name,
        'kind': kind,
        'dir': asset_id,
        'glb': glb,
        'blend': blend,
        'sheet': sheet_name,
        # ROOT-relative, like mesh_skeletons' previews/mesh3d: these two are what the
        # GUI fetches through /mesh/img?root=props, whose containment check resolves
        # against the registry root, not against one asset's folder.
        'mesh3d': (asset_id + '/mesh3d.bin' if os.path.isfile(os.path.join(dst, 'mesh3d.bin')) else None),
        'creature_id': creature_id,
        'description': description,
        'tags': list(tags),
        'previews': [asset_id + '/beauty/' + f for f in ordered],
        'views': {
            'ids': ids,
            'beauty': len(beauty),
            'passes': len(passes),
            'pass_kinds': list(_PASS_KINDS) if passes else [],
        },
        'geometry': stats,
        'licence': licence or {},
        'provenance': dict(provenance or {}, registered=registered or ''),
        'sha256': hashes,
        'bytes': sum(os.path.getsize(os.path.join(dst, r)) for r in hashes),
    }
    with _LOCK:
        reg = load_registry()
        reg.setdefault('schema', SCHEMA)
        reg.setdefault('assets', {})[asset_id] = rec
        _save_registry(reg)
    rec = dict(rec)
    rec['id'] = asset_id
    return rec


def beauty_path_local(d, view_id):
    for ext in _IMG_EXT:
        p = os.path.join(d, 'beauty', view_id + ext)
        if os.path.isfile(p):
            return p
    return None


def pass_path_local(d, view_id, kind):
    pdir = os.path.join(d, 'passes')
    if not os.path.isdir(pdir):
        return None
    stem = '%s_%s_' % (view_id, kind)
    hits = sorted(f for f in os.listdir(pdir) if f.startswith(stem) and f.lower().endswith(_PASS_EXT))
    return os.path.join(pdir, hits[0]) if hits else None


if __name__ == '__main__':  # the CLI lives in prop_mesh_library_cli
    from zyg_workflows.prop_mesh_library_cli import _main as _cli_main

    raise SystemExit(_cli_main())
