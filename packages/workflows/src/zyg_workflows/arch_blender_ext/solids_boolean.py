# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""solids_boolean — Blender geometry for the 'csg' kind (2026-09-08).

The twin of arch_ext/solids_boolean.js. The tab cuts with its own BSP kernel;
Blender has a better one already, so this builder uses it: both operands are
made as real temporary objects and a BOOLEAN modifier with the EXACT solver
does the cut, then the evaluated mesh is read back into `bm` and the temporary
objects are deleted. (bmesh.ops has no boolean; the brief's fallback — bpy.ops
with a modifier — is the supported route and it runs inside Blender.)

LOCAL FRAME (arch_blender_build.build_kind): X along, Y = studio -Z, Z up,
bottom at z=0. An operand's studio offset (x, y, z) therefore becomes
(x, -z, y) and its rotation (rx, ry, rz) becomes the Euler (rx, -rz, ry) —
exactly what arch_blender_build.py does for a whole record.

APPROXIMATION, HONESTLY (prefix '~'). arch_blender_build.build_kind is not
exposed to an extension builder, so this file re-makes the operands from the
kit's own primitives. The kinds below are exact; ANY OTHER operand kind is
replaced by a box sized from whatever w/d/h/len/r/t its parameters carry, and
the result is prefixed '~'. The same '~' is used when the boolean itself
cannot run, in which case the geometry falls back to operand A alone.
"""

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


# Operand kinds this file can rebuild exactly, and how. Everything else gets
# a bounding box and a '~'.
_BOXY = {
    # kind:        (sx key, sy key, sz key, defaults)
    'box': ('w', 'd', 'h', (1.0, 1.0, 1.0)),
    'slab': ('w', 'd', 't', (6.0, 4.0, 0.22)),
    'roof_flat': ('w', 'd', 't', (8.0, 6.0, 0.3)),
    'footing': ('w', 'd', 't', (1.0, 1.0, 0.35)),
    'column_rect': ('w', 'd', 'h', (0.3, 0.3, 3.0)),
}
_ROUND = {
    # kind:          (r key, h key, defaults, r_top factor)
    'cylinder': ('r', 'h', (0.5, 1.0), 1.0),
    'column_round': ('r', 'h', (0.18, 3.0), 1.0),
    'cone': ('r', 'h', (0.5, 1.0), 0.0),
}


def _approx_size(p, kit):
    """A box for a kind we cannot rebuild: the largest plausible extent its
    numbers describe. Never zero — a zero-volume operand would delete the
    boolean instead of approximating it."""
    N = kit['num']
    r = N(p, 'r', 0.0)
    sx = N(p, 'w', 0.0) or N(p, 'len', 0.0) or (2 * r) or 1.0
    sy = N(p, 'd', 0.0) or N(p, 't', 0.0) or (2 * r) or 1.0
    sz = N(p, 'h', 0.0) or N(p, 't', 0.0) or (2 * r) or 1.0
    return abs(sx) or 1.0, abs(sy) or 1.0, abs(sz) or 1.0


def _operand(bm, kind, p, kit):
    """Fill `bm` with one operand in ITS OWN local frame. Returns True when the
    shape is exact, False when it is a bounding-box stand-in."""
    N = kit['num']
    kind = str(kind or '')
    if kind in _BOXY:
        kx, ky, kz, dfl = _BOXY[kind]
        kit['add_box_c'](bm, N(p, kx, dfl[0]), N(p, ky, dfl[1]), N(p, kz, dfl[2]), 0.0, 0.0, 0.0)
        return True
    if kind in _ROUND:
        kr, kh, dfl, top = _ROUND[kind]
        r = N(p, kr, dfl[0])
        h = N(p, kh, dfl[1])
        kit['add_cylinder'](bm, r, h, 0.0, max(3, int(N(p, 'seg', 32))), 0.0, 0.0, r * top if top else 0.0001)
        return True
    if kind == 'sphere':
        r = N(p, 'r', 0.5)
        kit['add_sphere'](bm, r, r, 0.0, 0.0, max(6, int(N(p, 'seg', 32))), max(4, int(N(p, 'seg', 32) / 2)))
        return True
    if kind == 'beam':
        kit['add_box_c'](bm, N(p, 'len', 5.0), N(p, 'w', 0.2), N(p, 'h', 0.4), 0.0, 0.0, 0.0)
        return True
    if kind == 'pyramid':
        kit['add_cylinder'](bm, N(p, 'r', 0.7), N(p, 'h', 1.0), 0.0, max(3, int(N(p, 'sides', 4))), 0.0, 0.0, 0.0001)
        return True
    sx, sy, sz = _approx_size(p, kit)
    kit['add_box_c'](bm, sx, sy, sz, 0.0, 0.0, 0.0)
    return False


def _placed(desc, kit):
    """A new bmesh holding one operand, moved/rotated/scaled into the csg
    record's own local frame. Returns (bmesh, exact)."""
    import mathutils

    bmesh = kit['bmesh']
    N = kit['num']
    d = desc if isinstance(desc, dict) else {}
    bm2 = bmesh.new()
    exact = _operand(bm2, d.get('kind'), d.get('p') or {}, kit)
    # studio (x, y, z) -> blender (x, -z, y); studio (rx, ry, rz) -> (rx, -rz, ry)
    loc = mathutils.Matrix.Translation((N(d, 'x', 0.0), -N(d, 'z', 0.0), N(d, 'y', 0.0)))
    rot = mathutils.Euler((N(d, 'rx', 0.0), -N(d, 'rz', 0.0), N(d, 'ry', 0.0)), 'XYZ').to_matrix().to_4x4()
    s = N(d, 's', 1.0) or 1.0
    scl = mathutils.Matrix.Diagonal((s, s, s, 1.0))
    bmesh.ops.transform(bm2, matrix=loc @ rot @ scl, verts=bm2.verts)
    return bm2, exact


def _to_object(bm2, name):
    import bpy

    me = bpy.data.meshes.new(name)
    bm2.to_mesh(me)
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def _drop(ob):
    import bpy

    try:
        me = ob.data
        bpy.context.scene.collection.objects.unlink(ob)
        bpy.data.objects.remove(ob, do_unlink=True)
        bpy.data.meshes.remove(me, do_unlink=True)
    except Exception as _exc:  # noqa: BLE001
        _zyg_log.warning('scratch solid removal failed — it may leak into the render: %s', _exc)


_MOD = {'union': 'UNION', 'subtract': 'DIFFERENCE', 'intersect': 'INTERSECT'}


def build_csg(bm, p, kit):
    import bpy

    op = str((p or {}).get('op') or 'subtract').lower()
    if op not in _MOD:
        op = 'subtract'
    a = (p or {}).get('a') or {'kind': 'box', 'p': {'w': 2, 'h': 2, 'd': 2}}
    b = (p or {}).get('b') or {'kind': 'cylinder', 'p': {'r': 0.6, 'h': 3}, 'y': -0.5}

    bm_a, exact_a = _placed(a, kit)
    bm_b, exact_b = _placed(b, kit)
    exact = exact_a and exact_b

    oa = ob = None
    try:
        oa = _to_object(bm_a, '_csg_a')
        ob = _to_object(bm_b, '_csg_b')
        mod = oa.modifiers.new('csg', 'BOOLEAN')
        mod.operation = _MOD[op]
        mod.object = ob
        try:
            mod.solver = 'EXACT'
        except (AttributeError, TypeError):  # older Blender: BMesh solver only
            exact = False
        dg = bpy.context.evaluated_depsgraph_get()
        out = bpy.data.meshes.new_from_object(oa.evaluated_get(dg))
        bm.from_mesh(out)
        bpy.data.meshes.remove(out, do_unlink=True)
    except Exception as e:  # noqa: BLE001
        # The cut failed — keep operand A rather than losing the object, and say
        # so with '~'. An approximate object in the outliner is a question, not
        # a lie; an empty one is a lost drawing.
        _zyg_log.info('[solids_boolean] boolean failed (%r) — keeping operand A' % (e,))
        bm.clear()
        _copy(bm_a, bm)
        exact = False
    finally:
        if oa is not None:
            _drop(oa)
        if ob is not None:
            _drop(ob)
        bm_a.free()
        bm_b.free()

    bm.normal_update()
    return ('' if exact else '~', [])


def _copy(src, dst):
    """Append every face of `src` to `dst` (no bpy needed)."""
    src.verts.index_update()
    vmap = {v.index: dst.verts.new((v.co.x, v.co.y, v.co.z)) for v in src.verts}
    for f in src.faces:
        try:
            dst.faces.new([vmap[v.index] for v in f.verts])
        except ValueError as _exc:  # a duplicate face
            _zyg_log.debug('duplicate face skipped: %s', _exc)


BUILDERS = {'csg': build_csg}
