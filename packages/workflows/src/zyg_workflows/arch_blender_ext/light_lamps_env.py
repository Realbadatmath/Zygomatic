# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""light_lamps_env — Blender geometry (and real lamps) for the Lighting family.

Local frame (see arch_blender_build.build_kind): X along, Y = studio -Z (depth),
Z up. The three lamp kinds break the usual "bottom at z = 0" rule for the SAME
reason the tab's arch_ext/light_lamps_env.js does: the record's own origin is
where the photons come from, so the fitting sits ON it. A 0.25 m EMISSIVE disc
for the point light (2026-09-16; the tab keeps its marker sphere), a beam-wide
cone hanging under the origin for the spot, a thin plate for the area light.

*** WHERE THE REAL LAMP LANDS ***
Each builder ALSO creates a genuine bpy light datablock (POINT / SPOT / AREA,
named 'light:<kind>') with the record's colour, power, range and cone, so an
exported .blend renders with light in it and not only with markers. But a
builder is handed ONLY `bm` and `p`: arch_blender_build applies the record's
x/y/z and rotation to the MESH object it wraps around bm, never to an object a
builder made itself. So the lamp object lands at the DRAWING ORIGIN, not under
its marker, until the sweep's builder gains a transform hook. The marker mesh is
in the right place; the lamp is not. Move it in Blender, or read the marker's
transform, until that hook exists.

Watts-ish -> Blender: a point/spot lamp's `energy` is in watts and a Cycles
point light of P watts is roughly the studio's `w`, so w is passed through
(x10 for the area light's much larger emitting surface would over-light a room,
so it is passed through as well). This is a look, not a photometric simulation.
"""

import math

_COL = {'light_point': (1.0, 0.914, 0.769), 'light_spot': (1.0, 0.914, 0.769), 'light_area': (1.0, 0.914, 0.769)}
MARKER_R = 0.06  # a 0.12 m marker, as in the tab

# 2026-09-16 — the ceiling fitting. The lobby render showed every light_point
# as a grey marker sphere in mat_plaster: a room full of downlights that do not
# look lit. A point light is now a small EMISSIVE disc, so the fitting reads as
# a light source in the frame as well as pushing photons. arch_ext's tab
# drawing is unchanged — the marker sphere is still the right thing in a
# wireframe viewport.
EMIT_MAT = 'zyg_lamp_emissive'  # the key it is cached under in arch_blender_build._MATERIALS
EMIT_COL = (1.0, 0.93, 0.80)  # warm white
EMIT_STRENGTH = 8.0
DISC_D = 0.25  # the fitting is 0.25 m across
DISC_T = 0.02


def _hex_rgb(v, default):
    s = str(v or '').strip().lstrip('#')
    if len(s) == 3:
        s = ''.join(c * 2 for c in s)
    if len(s) != 6:
        return default
    try:
        return (int(s[0:2], 16) / 255.0, int(s[2:4], 16) / 255.0, int(s[4:6], 16) / 255.0)
    except ValueError:
        return default


def _lamp(kind, p, num):
    """The real bpy light. Returns the object, or None when bpy is unavailable
    (the geometry half must never fail because of it)."""
    try:
        import bpy
    except ImportError:
        return None
    lt = {'light_point': 'POINT', 'light_spot': 'SPOT', 'light_area': 'AREA'}[kind]
    try:
        data = bpy.data.lights.new(name='light:' + kind, type=lt)
        data.color = _hex_rgb(p.get('col'), _COL[kind])
        data.energy = max(0.1, num(p, 'w', 12.0))
        if lt == 'SPOT':
            data.spot_size = 2.0 * math.radians(min(80.0, max(3.0, num(p, 'angle', 35.0))))
            data.spot_blend = min(1.0, max(0.0, num(p, 'pen', 0.3)))
        elif lt == 'AREA':
            data.shape = 'RECTANGLE'
            data.size = max(0.05, num(p, 'x', 1.0))
            data.size_y = max(0.05, num(p, 'z', 0.6))
        else:
            data.shadow_soft_size = 0.05
        obj = bpy.data.objects.new('light:' + kind, data)
        obj['studio_light'] = kind
        obj['studio_note'] = 'at the drawing origin: a builder cannot see the record transform'
        (bpy.context.scene.collection).objects.link(obj)
        return obj
    except Exception:  # noqa: BLE001
        return None  # a lamp is a bonus, never a build failure


def _emissive(kit):
    """Register the emission material in arch_blender_build's OWN material
    cache and hand back its id, so the record loop hangs it on the disc's
    second slot (get_material returns anything already in that cache). Returns
    '' when bpy or the cache is out of reach — the disc then keeps the record's
    own material and nothing fails."""
    try:
        import bpy

        cache = kit['num'].__globals__['_MATERIALS']
    except Exception:  # noqa: BLE001
        return ''
    try:
        if EMIT_MAT not in cache:
            m = bpy.data.materials.new(EMIT_MAT)
            m.use_nodes = True
            nt = m.node_tree
            out = nt.nodes.get('Material Output')
            for n in list(nt.nodes):
                if n is not out:
                    nt.nodes.remove(n)
            em = nt.nodes.new('ShaderNodeEmission')
            em.inputs['Color'].default_value = (EMIT_COL[0], EMIT_COL[1], EMIT_COL[2], 1.0)
            em.inputs['Strength'].default_value = EMIT_STRENGTH
            nt.links.new(em.outputs['Emission'], out.inputs['Surface'])
            cache[EMIT_MAT] = m
        return EMIT_MAT
    except Exception:  # noqa: BLE001
        return ''


def build_light_point(bm, p, kit):
    """A flush 0.25 m emissive disc, not a marker sphere. The record's origin is
    where the photons come from, so the disc's TOP sits on it and the lit face
    looks down into the room. The real POINT lamp is unchanged."""
    mid = _emissive(kit)
    kit['add_cylinder'](bm, DISC_D / 2.0, DISC_T, z0=-DISC_T, seg=24, mi=1 if mid else 0)
    _lamp('light_point', p, kit['num'])
    return ('~', [mid] if mid else [])  # '~' = a fitting, not a surface: keep it out of the BOM prefixes


SPOT_D = 0.12  # a recessed downlight's visible ring


def build_light_spot(bm, p, kit):
    """A flush 0.12 m emissive downlight ring, the real SPOT lamp unchanged.
    Until 2026-09-16 this was the tab's 0.18 m cone marker, and under a glass
    canopy six of them read as white bow-ties in every approach render (job
    5e7eb915e1f9); the cone stays the tab's icon, the render gets a fitting."""
    mid = _emissive(kit)
    kit['add_cylinder'](bm, SPOT_D / 2.0, DISC_T, z0=-DISC_T, seg=18, mi=1 if mid else 0)
    _lamp('light_spot', p, kit['num'])
    return ('~', [mid] if mid else [])


def build_light_area(bm, p, kit):
    w = min(20.0, max(0.05, kit['num'](p, 'x', 1.0)))
    d = min(20.0, max(0.05, kit['num'](p, 'z', 0.6)))
    kit['add_box_c'](bm, w, d, 0.03, z0=-0.015)
    _lamp('light_area', p, kit['num'])
    return ('~', [])


BUILDERS = {'light_point': build_light_point, 'light_spot': build_light_spot, 'light_area': build_light_area}
