#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""mesh_pack_dims.py — measure every GLB / glTF in the mesh packs and write a
DIMENSIONS.json per pack: {rel_path: [width_x, height_y, depth_z] in metres}
plus {rel_path: triangle_count}.

Why (2026-09-07): the catalogue reported 1 x 1 x 1 m for all 7,312 items, so
a placed palm was one metre tall and the assistant's search results carried no
usable size. A model without a stated size reads as a toy no matter how good
it is. This measures the real world-space bounding box from the file itself —
no Blender, no numpy: glTF stores min/max per POSITION accessor, and the scene
graph's node matrices are applied to the eight corners of each primitive's
box. That is exact for boxes under affine transforms, which is all glTF has.

    python3 mesh_pack_dims.py            # all packs, skips files already measured
    python3 mesh_pack_dims.py --force    # re-measure everything
    python3 mesh_pack_dims.py kenney/nature-kit polyhaven   # only these pack dirs

Output: <pack_dir>/DIMENSIONS.json, read by architecture_assets._scan_pack()
into p.bw / p.bh / p.bd. Units are glTF units, which the spec fixes as metres.

The sibling key 'tris' (2026-09-11) is the triangle count of each file, taken
from the same parse. Without it nothing downstream could budget: a live job put
four jacarandas of 3,863,832 triangles each into one scene — 15.5 M of the
scene's 15.66 M — because the catalogue had no idea what a model costs.
"""

from __future__ import annotations

import json
import math
import os
import re
import struct
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PACKS_ROOT = os.path.realpath(os.path.join(HERE, 'data', 'assets', 'mesh_packs'))
MESH_EXT = ('.glb', '.gltf')
SKIP = ('_generated_previews', '__MACOSX', 'Sources', 'Source', 'OBJ', 'FBX')


def _mat_mul(a, b):
    """4x4 column-major (glTF) matrices as 16-lists: a @ b."""
    out = [0.0] * 16
    for c in range(4):
        for r in range(4):
            out[c * 4 + r] = sum(a[k * 4 + r] * b[c * 4 + k] for k in range(4))
    return out


def _mat_from_trs(node):
    if 'matrix' in node:
        return list(map(float, node['matrix']))
    t = node.get('translation', [0, 0, 0])
    q = node.get('rotation', [0, 0, 0, 1])
    s = node.get('scale', [1, 1, 1])
    x, y, z, w = q
    # rotation matrix (column-major)
    r = [
        1 - 2 * (y * y + z * z),
        2 * (x * y + z * w),
        2 * (x * z - y * w),
        0,
        2 * (x * y - z * w),
        1 - 2 * (x * x + z * z),
        2 * (y * z + x * w),
        0,
        2 * (x * z + y * w),
        2 * (y * z - x * w),
        1 - 2 * (x * x + y * y),
        0,
        0,
        0,
        0,
        1,
    ]
    for c in range(3):  # scale the columns
        for rr in range(3):
            r[c * 4 + rr] *= s[c]
    r[12], r[13], r[14] = t
    return r


def _xform(m, p):
    x, y, z = p
    return (
        m[0] * x + m[4] * y + m[8] * z + m[12],
        m[1] * x + m[5] * y + m[9] * z + m[13],
        m[2] * x + m[6] * y + m[10] * z + m[14],
    )


def load_gltf_json(path: str) -> dict | None:
    with open(path, 'rb') as fh:
        head = fh.read(12)
        if head[:4] == b'glTF':
            _magic, _ver, _len = struct.unpack('<III', head)
            clen, ctype = struct.unpack('<II', fh.read(8))
            if ctype != 0x4E4F534A:  # JSON
                return None
            return json.loads(fh.read(clen).decode('utf-8', 'replace'))
        fh.seek(0)
        try:
            return json.load(fh)
        except ValueError:
            return None


def measure(path: str, g: dict | None = None) -> list | None:
    """[w, h, d] of the default scene (or all root nodes) in glTF units."""
    if g is None:
        g = load_gltf_json(path)
    if not g or not g.get('meshes') or not g.get('accessors'):
        return None
    acc = g['accessors']
    meshes = g['meshes']
    nodes = g.get('nodes') or []
    lo = [math.inf] * 3
    hi = [-math.inf] * 3

    def take_mesh(mi, m):
        for prim in meshes[mi].get('primitives') or []:
            ai = (prim.get('attributes') or {}).get('POSITION')
            if ai is None or ai >= len(acc):
                continue
            a = acc[ai]
            mn, mx = a.get('min'), a.get('max')
            if not mn or not mx or len(mn) < 3:
                continue
            for cx in (mn[0], mx[0]):
                for cy in (mn[1], mx[1]):
                    for cz in (mn[2], mx[2]):
                        px, py, pz = _xform(m, (cx, cy, cz))
                        for i, v in enumerate((px, py, pz)):
                            if v < lo[i]:
                                lo[i] = v
                            if v > hi[i]:
                                hi[i] = v

    seen = set()

    def walk(ni, parent, depth=0):
        if ni in seen or depth > 64 or ni >= len(nodes):
            return
        seen.add(ni)
        n = nodes[ni]
        m = _mat_mul(parent, _mat_from_trs(n))
        if 'mesh' in n and n['mesh'] < len(meshes):
            take_mesh(n['mesh'], m)
        for c in n.get('children') or []:
            walk(c, m, depth + 1)

    ident = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
    scenes = g.get('scenes') or []
    roots = []
    if scenes:
        si = g.get('scene', 0)
        roots = (scenes[si] if si < len(scenes) else scenes[0]).get('nodes') or []
    if not roots:
        children = {c for n in nodes for c in (n.get('children') or [])}
        roots = [i for i in range(len(nodes)) if i not in children]
    for r in roots:
        walk(r, ident)
    if not nodes:  # meshes but no nodes: measure them raw
        for mi in range(len(meshes)):
            take_mesh(mi, ident)
    if lo[0] is math.inf:
        return None
    dims = [round(hi[i] - lo[i], 4) for i in range(3)]
    if any(d < 0 or math.isnan(d) for d in dims):
        return None
    return dims


# Triangle modes in glTF: 4 TRIANGLES (the default), 5 STRIP, 6 FAN. Modes
# 0-3 are points and lines and contribute no triangles at all.
_TRI_MODES = (4, 5, 6)


def count_tris(g: dict) -> int:
    """Triangles in one glTF document, summed over every mesh primitive.

    Counted per MESH, not per node instance: this is the cost of the file, and
    a renderer that draws the same mesh twice pays for one upload. Indices give
    the exact count; a non-indexed primitive draws its POSITION accessor."""
    acc = g.get('accessors') or []
    total = 0
    for mesh in g.get('meshes') or []:
        for prim in mesh.get('primitives') or []:
            mode = prim.get('mode', 4)
            if mode not in _TRI_MODES:
                continue
            ai = prim.get('indices')
            if ai is None:
                ai = (prim.get('attributes') or {}).get('POSITION')
            if ai is None or ai >= len(acc):
                continue
            n = int(acc[ai].get('count') or 0)
            total += (n // 3) if mode == 4 else max(0, n - 2)
    return total


def measure_file(path: str) -> tuple:
    """(dims, tris) from ONE parse of the document — the 208 MB jacaranda is
    not worth opening twice."""
    g = load_gltf_json(path)
    if not g:
        return None, None
    return measure(path, g), count_tris(g)


LICENCE_FILE = re.compile(r'^(licen[cs]e|license_evidence|copying)[^/]*\.(txt|md)$', re.I)


def _packlike(d: str) -> bool:
    """Same rule as architecture_assets._build: a sub-directory is a PACK when it
    ships its own licence file or a PROVENANCE.json; otherwise the vendor dir
    is one pack whose sub-directories are items (polyhaven_arch, ambientcg)."""
    try:
        names = os.listdir(d)
    except OSError:
        return False
    return 'PROVENANCE.json' in names or any(LICENCE_FILE.match(n) for n in names)


def pack_dirs(only: list[str]) -> list[str]:
    out = []
    for vendor in sorted(os.listdir(PACKS_ROOT)):
        vd = os.path.join(PACKS_ROOT, vendor)
        if not os.path.isdir(vd) or vendor in SKIP or vendor.startswith(('_', '.')):
            continue
        subs = [
            d for d in sorted(os.listdir(vd)) if os.path.isdir(os.path.join(vd, d)) and not d.startswith(('_', '.'))
        ]
        packlike = [s for s in subs if _packlike(os.path.join(vd, s))]
        cands = [os.path.join(vd, s) for s in packlike] if packlike else [vd]
        for c in cands:
            rel = os.path.relpath(c, PACKS_ROOT)
            if only and not any(
                rel == o or rel.startswith(o.rstrip('/') + '/') or rel.split('/')[0] == o for o in only
            ):
                continue
            out.append(c)
    return out


def run(only: list[str], force: bool) -> dict:
    t0 = time.time()
    total = measured = failed = kept = 0
    for pd in pack_dirs(only):
        dpath = os.path.join(pd, 'DIMENSIONS.json')
        old, old_tris = {}, {}
        if os.path.exists(dpath) and not force:
            try:
                prev = json.load(open(dpath, encoding='utf-8'))
                old = prev.get('dims') or {}
                old_tris = prev.get('tris') or {}
            except Exception:  # noqa: BLE001
                old, old_tris = {}, {}
        dims, tris = dict(old), dict(old_tris)
        for root, dirs, files in os.walk(pd):
            dirs[:] = [d for d in dirs if d not in SKIP and not d.startswith('_')]
            for f in files:
                if not f.lower().endswith(MESH_EXT):
                    continue
                rel = os.path.relpath(os.path.join(root, f), pd).replace(os.sep, '/')
                total += 1
                # a file measured before the triangle count existed is re-read
                if rel in dims and rel in tris and not force:
                    kept += 1
                    continue
                try:
                    d, n = measure_file(os.path.join(root, f))
                except Exception:  # noqa: BLE001
                    d, n = None, None
                if d:
                    dims[rel] = d
                    tris[rel] = int(n or 0)
                    measured += 1
                else:
                    failed += 1
        if dims:
            with open(dpath, 'w', encoding='utf-8') as fh:
                json.dump(
                    {
                        'unit': 'm',
                        'axes': 'x width, y height, z depth (glTF Y-up)',
                        'measured': time.strftime('%Y-%m-%d'),
                        'method': 'POSITION accessor min/max under the scene-graph node matrices',
                        'dims': dims,
                        'tris': tris,
                    },
                    fh,
                    indent=0,
                )
    return {'files': total, 'measured': measured, 'kept': kept, 'failed': failed, 'seconds': round(time.time() - t0, 1)}


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    print(json.dumps(run(args, '--force' in sys.argv)))
