# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""groom_to_glb.py — a Blender Studio character's hair groom -> a ribbon GLB
in the SKULL FRAME.
blender -b --factory-startup <char.blend> --python groom_to_glb.py -- <out_dir> <char_id> [max_strands]

WHAT IS EXPORTED. Not the guides. A Blender Studio groom is 10 to 85 guide
strands multiplied at render time into thousands of children, and the guides
alone are a handful of wires that look nothing like the hair. Legacy particle
systems are therefore converted through curves.convert_from_particle_system(),
which bakes the children, and the new Curves objects (Einar) are read straight
off. Every strand is then resampled to a fixed sample count and a fixed number
of strands is kept, so a groom lands inside a triangle budget the viewport can
actually draw instead of inside the film's.

THE SKULL FRAME. A groom is stored relative to the SKULL it grew on: a
least-squares sphere fitted to the surface the hair is rooted in. The origin is
that sphere's centre and one unit is its radius. Fitting the groom to Character
Studio's clay head is then a translate and a uniform scale off the same fit
taken on the clay skull — measured on both sides, never a guessed proportion.
The forward axis comes with it, so a groom cannot arrive facing backwards
without the number saying so.

RIBBONS, NOT LINES. Each strand becomes a tapered flat ribbon whose width runs
along cross(tangent, outward-from-skull), so it presents its face to a camera
outside the head. Colour is left to the studio: the material is plain, and
char_hair.js recolours it from the operator's hair-colour tool."""

import json
import logging as _zyg_logging
import math
import os
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# The part rule lives in hair_parts.py so char_cycles_render.py finds the SAME
# grooms at full density in the source .blend that this baked into ribbons.
from hair_parts import kind as _kind_of  # noqa: E402  needs the sys.path above under --factory-startup

_zyg_log = _zyg_logging.getLogger(__name__)

DOME_FRAC = 0.45  # must match hair_extract.py, cycles_render.py and char_hair.js


def _kind(nm):
    """See hair_parts.kind — one rule, two consumers."""
    return _kind_of(nm)


# The three helpers below mirror hair_extract.py rather than import it:
# hair_extract.py calls main() at module level, so importing it would run a
# whole extraction. sphere_fit is already duplicated for the same reason.
def ensure_visible(ob):
    """True once `ob` is reachable from the view layer, linking it if it is not."""
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


def _dome(pts):
    """The top DOME_FRAC of a surface's own height — a skull cap, not a head."""
    if not pts:
        return pts
    zs = [p.z for p in pts]
    top, bot = max(zs), min(zs)
    sel = [p for p in pts if p.z >= top - DOME_FRAC * (top - bot)]
    return sel if len(sel) >= 8 else pts


def sphere_fit(pts):
    """Least-squares sphere through points: returns (centre, radius).

    The linear form: |p|^2 = 2c.p + (r^2 - |c|^2), solved for (cx, cy, cz, k)
    by normal equations. Four unknowns, so any real scalp cap is plenty."""
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
    # Gaussian elimination with partial pivoting
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
    if r2 <= 0:
        return None, None
    return centre, math.sqrt(r2)


def resample(pts, n):
    """A polyline resampled to n points by arc length."""
    if len(pts) < 2:
        return None
    seg = [0.0]
    for i in range(1, len(pts)):
        seg.append(seg[-1] + (pts[i] - pts[i - 1]).length)
    total = seg[-1]
    if total <= 1e-9:
        return None
    out, j = [], 0
    for k in range(n):
        d = total * k / (n - 1)
        while j < len(seg) - 2 and seg[j + 1] < d:
            j += 1
        span = seg[j + 1] - seg[j]
        t = 0.0 if span <= 1e-12 else (d - seg[j]) / span
        out.append(pts[j].lerp(pts[j + 1], t))
    return out


def strands_from_curves(ob, dg):
    """World-space polylines of a Curves object."""
    ev = ob.evaluated_get(dg)
    cs = ev.data
    mw = ob.matrix_world
    pos = [mw @ Vector(p.position) for p in cs.points]
    out = []
    for c in cs.curves:
        a = c.first_point_index
        n = c.points_length
        if n >= 2:
            out.append(pos[a : a + n])
    return out


def strands_from_particles(ob, psys_name, dg):
    """World-space polylines of ONE particle system, children included.

    curves.convert_from_particle_system() bakes what the renderer would draw;
    the guides on their own are 10 to 85 wires."""
    if not ensure_visible(ob):
        return [], f'{ob.name}/{psys_name}: not reachable from the view layer'
    deselect_all()
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    idx = [p.name for p in ob.particle_systems].index(psys_name)
    ob.particle_systems.active_index = idx
    before = set(o.name for o in bpy.context.scene.objects)
    try:
        bpy.ops.curves.convert_from_particle_system()
    except Exception as e:  # noqa: BLE001
        return [], f'{ob.name}/{psys_name}: convert failed {e!r}'
    new = [o for o in bpy.context.scene.objects if o.name not in before]
    if not new:
        return [], f'{ob.name}/{psys_name}: convert produced nothing'
    dg2 = bpy.context.evaluated_depsgraph_get()
    out = []
    for o in new:
        if o.type == 'CURVES':
            out.extend(strands_from_curves(o, dg2))
    for o in new:
        bpy.data.objects.remove(o, do_unlink=True)
    return out, None


def ribbons(strands, centre, radius, samples, width, taper=0.18):
    """Tapered flat ribbons, one per strand, in SKULL UNITS."""
    verts, tris, nrms = [], [], []
    for sp in strands:
        rs = resample(sp, samples)
        if rs is None:
            continue
        base = len(verts)
        for k, p in enumerate(rs):
            nxt = rs[min(k + 1, samples - 1)]
            prv = rs[max(k - 1, 0)]
            tan = nxt - prv
            if tan.length < 1e-9:
                tan = Vector((0.0, 0.0, 1.0))
            tan.normalize()
            out = p - centre
            if out.length < 1e-9:
                out = Vector((0.0, 0.0, 1.0))
            out.normalize()
            side = tan.cross(out)
            if side.length < 1e-9:
                side = tan.cross(Vector((0.0, 0.0, 1.0)))
            if side.length < 1e-9:
                side = Vector((1.0, 0.0, 0.0))
            side.normalize()
            t = k / (samples - 1.0)
            w = width * (1.0 - (1.0 - taper) * t) * 0.5
            q = (p - centre) / radius
            s = side * (w)
            verts.append(q - s)
            verts.append(q + s)
            nrms.append(out)
            nrms.append(out)
        for k in range(samples - 1):
            a = base + k * 2
            tris.append((a, a + 1, a + 3))
            tris.append((a, a + 3, a + 2))
    return verts, tris, nrms


# A ribbon stands in for many hairs, so it widens as the kept strand count
# falls — but only so far. Ellie's 'loose' system is 40 strays, and the
# unclamped rule gave them ribbons a fifth of a skull wide: forty planks.
# A strand that runs further than this from the skull centre is a flyaway or a
# stray from a rigged emitter, not part of the shape. Waist-length hair reaches
# about 8 radii, so this only catches the wild ones.
CLIP_RADII = 9.0
# A hair is ROOTED in the scalp, so its first point sits about one skull radius
# from the centre. Ellie's groom is driven by an embedded rig script that
# --factory-startup refuses to run, and without it part of the groom evaluates
# displaced: her bounding box ran 4.4 skull radii to the left and 1.1 to the
# right, which no haircut does. Testing the ROOT catches exactly those strands
# and leaves long hair alone, where testing the length cannot tell them apart.
ROOT_RADII = 1.6


def _sane(strand, centre, radius):
    if not strand:
        return False
    if (strand[0] - centre).length > ROOT_RADII * radius:
        return False
    return all((p - centre).length <= CLIP_RADII * radius for p in strand)


W_MAX = 0.035


def _width(kind, kept):
    w = (0.020 if kind == 'hair' else 0.012) * math.sqrt(4000.0 / max(1, kept))
    return min(w, W_MAX)


def main():
    argv = sys.argv[sys.argv.index('--') + 1 :]
    out_dir, char_id = argv[0], argv[1]
    max_strands = int(argv[2]) if len(argv) > 2 else 8000
    samples = int(argv[3]) if len(argv) > 3 else 12
    os.makedirs(out_dir, exist_ok=True)

    dg = bpy.context.evaluated_depsgraph_get()
    jobs, problems = [], []

    # (a) new-style Curves objects
    for ob in list(bpy.context.scene.objects):
        if ob.type != 'CURVES' or len(ob.data.curves) < 8:
            continue
        nm = ob.name.lower()
        # No separate SKIP_KEYS test: hair_parts.kind() already returns None for
        # them, and the second copy of the rule is what drifts.
        kind = _kind(nm)
        if kind is None:
            continue
        surf = getattr(ob.data, 'surface', None)
        jobs.append({'src': 'curves', 'ob': ob, 'ps': None, 'surface': surf, 'name': ob.name, 'kind': kind})

    # (b) legacy particle systems
    for ob in list(bpy.context.scene.objects):
        for ps in list(getattr(ob, 'particle_systems', [])):
            if ps.settings.type != 'HAIR':
                continue
            nm = (ob.name + '/' + ps.name).lower()
            kind = _kind(nm)
            if kind is None:
                continue
            jobs.append(
                {
                    'src': 'particles',
                    'ob': ob,
                    'ps': ps.name,
                    'surface': ob,
                    'name': f'{ob.name}/{ps.name}',
                    'kind': kind,
                }
            )

    # The skull: fitted to the surface the hair is rooted in. One fit per
    # emitter, shared by every system on it, so the parts of one groom stay in
    # register with each other.
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
        # THE DOME, not the whole surface. Einar's hair is rooted in his head
        # MESH, so a sphere through all of it took in the face and neck and came
        # back too large; the groom normalised by that radius arrived a third of
        # the size of the clay skull and sat on the crown like a toupee. The
        # client fits its sphere to the top of the head band, so the donor has
        # to be measured the same way: the top DOME_FRAC of the surface's own
        # height, on both sides.
        pts = _dome(pts)
        c, r = sphere_fit(pts)
        if c is not None:
            skulls[s.name] = (c, r, len(pts))

    # ONE GLB PER HAIRSTYLE. The parts of a groom are separate systems on one
    # scalp — Ellie's front, back, ponytail and loose are four systems and one
    # haircut — so they are merged into a single asset keyed by the surface
    # they share. Brows and lashes stay their own asset; they are worn with any
    # hairstyle, and Character Studio already has its own brows.
    groups = {}
    for j in jobs:
        s_ob = j['surface']
        if s_ob is None:
            problems.append(f'{j["name"]}: no surface')
            continue
        groups.setdefault((s_ob.name, j['kind']), []).append(j)

    TRI_BUDGET = 220_000

    recs = []
    for (surf_name, kind), js in sorted(groups.items()):
        fit = skulls.get(surf_name)
        if not fit:
            problems.append(f'{surf_name}: no skull fit')
            continue
        centre, radius, npts = fit
        verts, tris, parts = [], [], []
        for j in js:
            if j['src'] == 'curves':
                sp, err = strands_from_curves(j['ob'], dg), None
            else:
                sp, err = strands_from_particles(j['ob'], j['ps'], dg)
            if err:
                problems.append(err)
                continue
            total = len(sp)
            if total < 8:
                problems.append(f'{j["name"]}: {total} strands, skipped')
                continue
            # share the budget between the systems of this groom
            per = max(400, min(max_strands, int(TRI_BUDGET / (2.0 * (samples - 1) * max(1, len(js))))))
            step = max(1, int(math.ceil(total / float(per))))
            kept = sp[::step][:per]
            kept = [k for k in kept if _sane(k, centre, radius)]
            if not kept:
                problems.append(f'{j["name"]}: every strand beyond the clip radius')
                continue
            w = _width(kind, len(kept))
            v2, t2, _n2 = ribbons(kept, centre, radius, samples, w)
            base = len(verts)
            verts.extend(v2)
            tris.extend([(a + base, b + base, c + base) for a, b, c in t2])
            parts.append({'name': j['name'], 'strands_total': total, 'strands_kept': len(kept), 'ribbon_width': w})
        if not tris:
            problems.append(f'{surf_name}: no ribbons')
            continue

        me = bpy.data.meshes.new(surf_name)
        me.from_pydata([tuple(v) for v in verts], [], tris)
        me.update()
        ob2 = bpy.data.objects.new(surf_name, me)
        bpy.context.scene.collection.objects.link(ob2)
        deselect_all()
        ob2.select_set(True)
        bpy.context.view_layer.objects.active = ob2
        stem = surf_name.replace('GEO-', '').replace('GEO_', '')
        stem = stem.replace('.scalp', '').replace('/', '_').replace('.', '_')
        fid = f'{char_id}_{stem}' if not stem.startswith(char_id) else stem
        # The part goes in the NAME, not just the record: Einar's hair and his
        # beard share one scalp, so both wrote einar_head.glb and the second
        # silently replaced the first.
        if kind != 'hair' or not fid.endswith('_hair'):
            fid = f'{fid}_{kind}'
        glb = os.path.join(out_dir, fid + '.glb')
        bpy.ops.export_scene.gltf(
            filepath=glb,
            export_format='GLB',
            use_selection=True,
            export_yup=True,
            export_materials='NONE',
            export_normals=True,
        )
        lo = [min(v[i] for v in verts) for i in range(3)]
        hi = [max(v[i] for v in verts) for i in range(3)]
        recs.append(
            {
                'id': fid,
                'file': os.path.basename(glb),
                'kind': 'strands',
                'part': kind,
                'character': char_id,
                'parts': parts,
                'strands_kept': sum(p['strands_kept'] for p in parts),
                'strands_total': sum(p['strands_total'] for p in parts),
                'samples': samples,
                'verts': len(verts),
                'tris': len(tris),
                'skull_surface': surf_name,
                'skull_surface_verts': npts,
                'skull_radius_blender': radius,
                # Blender +Z up -> glTF +Y up
                'bbox_skull_units': {'x': [lo[0], hi[0]], 'y': [lo[2], hi[2]], 'z': [-hi[1], -lo[1]]},
                'bytes': os.path.getsize(glb),
            }
        )
        bpy.data.objects.remove(ob2, do_unlink=True)

    print('ZYGRESULT' + json.dumps({'character': char_id, 'items': recs, 'problems': problems}))


main()
