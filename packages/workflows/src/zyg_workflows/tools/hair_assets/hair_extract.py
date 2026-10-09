# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""hair_extract.py — a character's groom at FULL density, in skull units.
blender -b --factory-startup <char.blend> --python hair_extract.py -- <out.npz> <char_id> [parts]

groom_to_glb.py bakes a DECIMATED ribbon version of the same grooms for the
three.js viewport: ~7,000 strands widened to 1.3 mm so the coverage still adds
up. That is a preview. This writes what Cycles should actually render — every
strand the groom has, at its own point count, with nothing widened and nothing
thrown away.

Stored in the donor's SKULL FRAME (origin at the centre of a least-squares
sphere through the top DOME_FRAC of the surface the hair is rooted in, one unit
= that radius), which is the same frame char_cycles_render.py measures on the
body it is about to render. Both sides measure; neither assumes.

Output .npz per part:
    pts     (N, 3) float32  all strand points, concatenated, in skull units
    starts  (S,)   int32    index of each strand's first point
    counts  (S,)   int32    points per strand
    meta    json blob: character, part, strand/point counts, donor radius
"""

import json
import math
import os
import sys

import numpy as np

import bpy
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hair_parts import kind as kind_of  # noqa: E402
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


DOME_FRAC = 0.45  # must match char_cycles_render.py and groom_to_glb.py


def ensure_visible(ob):
    if ob.name not in bpy.context.view_layer.objects:
        try:
            bpy.context.scene.collection.objects.link(ob)
        except RuntimeError:
            return False
    ob.hide_viewport = False
    try:
        ob.hide_set(False)
    except RuntimeError as _exc:
        _zyg_log.debug('unhiding %s skipped: %s', ob.name, _exc)
    return ob.name in bpy.context.view_layer.objects


def deselect_all():
    for o in bpy.context.view_layer.objects:
        try:
            o.select_set(False)
        except RuntimeError as _exc:
            _zyg_log.debug('deselecting %s skipped: %s', o.name, _exc)


def sphere_fit(pts):
    n = len(pts)
    if n < 8:
        return None, None
    A = [[0.0] * 4 for _ in range(4)]
    b = [0.0] * 4
    for p in pts:
        row = (2.0 * p[0], 2.0 * p[1], 2.0 * p[2], 1.0)
        rhs = p[0] * p[0] + p[1] * p[1] + p[2] * p[2]
        for i in range(4):
            for j in range(4):
                A[i][j] += row[i] * row[j]
            b[i] += row[i] * rhs
    M = [A[i][:] + [b[i]] for i in range(4)]
    for c in range(4):
        piv = max(range(c, 4), key=lambda r: abs(M[r][c]))
        if abs(M[piv][c]) < 1e-12:
            return None, None
        M[c], M[piv] = M[piv], M[c]
        for r in range(4):
            if r == c:
                continue
            f = M[r][c] / M[c][c]
            for k in range(c, 5):
                M[r][k] -= f * M[c][k]
    x = [M[i][4] / M[i][i] for i in range(4)]
    centre = Vector((x[0], x[1], x[2]))
    r2 = x[3] + centre.length_squared
    return (centre, math.sqrt(r2)) if r2 > 0 else (None, None)


def dome(pts):
    """The top DOME_FRAC of a surface's own height — a skull cap, not a head."""
    if not pts:
        return pts
    zs = [p.z for p in pts]
    top, bot = max(zs), min(zs)
    sel = [p for p in pts if p.z >= top - DOME_FRAC * (top - bot)]
    return sel if len(sel) >= 8 else pts


def strands_of_curves(ob, dg):
    ev = ob.evaluated_get(dg)
    cs = ev.data
    mw = ob.matrix_world
    pos = [mw @ Vector(p.position) for p in cs.points]
    out = []
    for c in cs.curves:
        a, n = c.first_point_index, c.points_length
        if n >= 2:
            out.append(pos[a : a + n])
    return out


def strands_of_particles(ob, ps_name):
    """Children baked, not the 10-85 guides."""
    if not ensure_visible(ob):
        return [], f'{ob.name}/{ps_name}: not reachable from the view layer'
    deselect_all()
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    ob.particle_systems.active_index = [p.name for p in ob.particle_systems].index(ps_name)
    before = {o.name for o in bpy.context.scene.objects}
    try:
        bpy.ops.curves.convert_from_particle_system()
    except Exception as e:  # noqa: BLE001
        return [], f'{ob.name}/{ps_name}: convert failed {e!r}'
    new = [o for o in bpy.context.scene.objects if o.name not in before]
    dg = bpy.context.evaluated_depsgraph_get()
    out = []
    for o in new:
        if o.type == 'CURVES':
            out.extend(strands_of_curves(o, dg))
    for o in new:
        bpy.data.objects.remove(o, do_unlink=True)
    return out, None


def main():
    argv = sys.argv[sys.argv.index('--') + 1 :]
    out_npz, char_id = argv[0], argv[1]
    want = set(argv[2].split(',')) if len(argv) > 2 and argv[2] else None

    dg = bpy.context.evaluated_depsgraph_get()
    jobs, problems = [], []
    for ob in list(bpy.context.scene.objects):
        if ob.type == 'CURVES' and len(ob.data.curves) >= 8:
            k = kind_of(ob.name)
            if k and (not want or k in want):
                jobs.append(
                    {
                        'src': 'curves',
                        'ob': ob,
                        'ps': None,
                        'surface': getattr(ob.data, 'surface', None),
                        'name': ob.name,
                        'kind': k,
                    }
                )
        for ps in list(getattr(ob, 'particle_systems', [])):
            if ps.settings.type != 'HAIR':
                continue
            k = kind_of(ob.name + '/' + ps.name)
            if k and (not want or k in want):
                jobs.append(
                    {
                        'src': 'particles',
                        'ob': ob,
                        'ps': ps.name,
                        'surface': ob,
                        'name': f'{ob.name}/{ps.name}',
                        'kind': k,
                    }
                )

    skulls = {}
    for j in jobs:
        s = j['surface']
        if s is None or s.name in skulls:
            continue
        try:
            ev = s.evaluated_get(dg)
            mw = s.matrix_world
            pts = [mw @ v.co for v in ev.data.vertices]
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.warning('skull surface %s skipped, its evaluated mesh is unavailable: %s', s.name, _exc)
            continue
        c, r = sphere_fit(dome(pts))
        if c is not None:
            skulls[s.name] = (c, r)

    # group by part, so 'hair' is one file however many systems make it up
    by_part = {}
    for j in jobs:
        by_part.setdefault(j['kind'], []).append(j)

    written = []
    for part, js in sorted(by_part.items()):
        pts_all, starts, counts = [], [], []
        n_pts = 0
        radius = None
        for j in js:
            s = j['surface']
            fit = skulls.get(s.name) if s is not None else None
            if not fit:
                problems.append(f'{j["name"]}: no skull fit')
                continue
            centre, r = fit
            radius = r
            if j['src'] == 'curves':
                sp, err = strands_of_curves(j['ob'], dg), None
            else:
                sp, err = strands_of_particles(j['ob'], j['ps'])
            if err:
                problems.append(err)
                continue
            for strand in sp:
                if len(strand) < 2:
                    continue
                # rooted on the scalp, and not a stray that flies off
                if (strand[0] - centre).length > 1.6 * r:
                    continue
                if any((p - centre).length > 9.0 * r for p in strand):
                    continue
                starts.append(n_pts)
                counts.append(len(strand))
                for p in strand:
                    q = (p - centre) / r
                    # Blender +Z up -> the glTF/studio convention +Y up
                    pts_all.append((q.x, q.z, -q.y))
                    n_pts += 1
        if not starts:
            problems.append(f'{part}: nothing kept')
            continue
        fp = out_npz.replace('.npz', f'_{part}.npz')
        os.makedirs(os.path.dirname(os.path.abspath(fp)), exist_ok=True)
        meta = {
            'character': char_id,
            'part': part,
            'strands': len(starts),
            'points': n_pts,
            'donor_skull_radius_m': radius,
            'sources': [j['name'] for j in js],
            'frame': 'skull_radius',
            'dome_frac': DOME_FRAC,
        }
        np.savez_compressed(
            fp,
            pts=np.asarray(pts_all, dtype=np.float32),
            starts=np.asarray(starts, dtype=np.int32),
            counts=np.asarray(counts, dtype=np.int32),
            meta=json.dumps(meta),
        )
        written.append(dict(meta, file=fp, bytes=os.path.getsize(fp)))

    print('ZYGEXTRACT' + json.dumps({'character': char_id, 'written': written, 'problems': problems}))


main()
