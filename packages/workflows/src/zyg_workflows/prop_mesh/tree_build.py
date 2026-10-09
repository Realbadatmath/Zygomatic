# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tree_build.py — Phase 2: the scarred oak, built from licence-checked geometry.

RUN:
    blender -b -P prop_mesh/tree_build.py -- --out output/axe_forest/tree \\
            [--cuts 24] [--seed 5] [--nu 384] [--nv 420] [--samples 96] [--no-axe]

WHAT CHANGED, AND WHY IT IS THE WHOLE POINT.
Every earlier attempt at this trunk asked an image model for bark and for wounds. Bark it
can do; wounds it cannot, and eleven attempts established that at length. Here both are
geometry and photography instead:

  bark      Poly Haven `bark_brown_02`, CC0 — diffuse, roughness, normal, AO and, the one
            that matters, DISPLACEMENT. The trunk is a real 384x420 surface displaced by
            that height map, so its fissures exist in the depth and normal passes. A normal
            map alone would look similar in the beauty render and measure as flat, and the
            gate measures.

  cuts      Boolean DIFFERENCE, one modifier per cutter, exactly as proven in
            prop_mesh/gate_proof.py (4.83% of the trunk changed, up to 48.5mm deep).

  cut faces `material_mode = 'TRANSFER'`, so the walls of each cut take the CUTTER's
            material rather than the bark. That is what puts photographed wood inside the
            wound instead of bark stretched over it. Fresh cuts get CC0 raw oak veneer;
            weathered cuts get the crop from the CC0 rubber-tapping panel. Two ages, two
            surfaces, because they are not the same surface.

CUT MATERIALS USE BOX PROJECTION, NOT UV. The cutter boxes have no UV layer, and a
transferred face carries the cutter's UVs — which would be degenerate. Object-space box
projection needs no UVs and maps at true world scale, so a 30mm cut shows 30mm of grain
rather than an entire texture squeezed into it. That is the same error class as the
2026-08-03 stretch, where a texture resized to the mask turned finger-width cuts into
forearm-width ones.

CUTTERS REACH FURTHER OUT THAN THE NOMINAL SURFACE. Displacement moves the bark by up to
+-22mm, so a cutter that starts exactly at the nominal radius misses the surface wherever a
fissure happens to be deep. Each one is extended 30mm outward, which is more than the
displacement amplitude, so every strike lands whatever the bark is doing underneath it.
"""

import json
import math
import os
import random
import sys
import tempfile

import bmesh
import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import hurlbat  # noqa: E402
import pass_lib  # noqa: E402
from zyg_workflows.geom import manifest as gmanifest  # noqa: E402
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


def _argv():
    a = sys.argv
    return a[a.index('--') + 1 :] if '--' in a else []


def _opt(args, name, default, cast=float):
    if name in args:
        try:
            return cast(args[args.index(name) + 1])
        except Exception:
            return default
    return default


def _flag(args, name):
    return name in args


ARGS = _argv()
OUT = _opt(ARGS, '--out', os.path.join(tempfile.gettempdir(), 'tree'), str)
W = int(_opt(ARGS, '--w', 1216))
H = int(_opt(ARGS, '--h', 704))
N_CUTS = int(_opt(ARGS, '--cuts', 38))
SEED = int(_opt(ARGS, '--seed', 5))
NU = int(_opt(ARGS, '--nu', 384))  # segments around the trunk
NV = int(_opt(ARGS, '--nv', 420))  # rows up the trunk
SAMPLES = int(_opt(ARGS, '--samples', 96))
TRUNK_R = _opt(ARGS, '--trunk-r', 0.42)
TRUNK_H = _opt(ARGS, '--trunk-h', 3.0)
# 0.085 was the decal script's value and it packed every scar behind the axe, where the
# hatchet hides them. The scars ARE the story — "he has stood here a hundred times" — so
# they spread wide enough to be seen around the current strike rather than under it.
CLUSTER_R = _opt(ARGS, '--cluster-r', 0.170)
AXE_X = _opt(ARGS, '--axe-x', 0.100)  # impact right of the centre line, so the trunk
AXE_Z = _opt(ARGS, '--axe-z', 0.020)  # already turns away and the strike reads oblique
BARK_TILE_M = _opt(ARGS, '--bark-tile', 1.2)  # metres covered by one bark texture repeat
DISP_M = _opt(ARGS, '--disp', 0.045)  # peak-to-peak bark relief, metres
CUT_REACH = 0.030  # how far outside the nominal radius cutters start
NO_AXE = _flag(ARGS, '--no-axe')

os.makedirs(OUT, exist_ok=True)
random.seed(SEED)

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene

MAN = gmanifest.Manifest()


def maps_for(asset_id):
    """Texture paths from the register — the licence-checked library is the only source.

    A missing asset is a hard stop rather than a silent grey fallback: a trunk that renders
    plain grey still produces a plausible-looking frame, and that is exactly the kind of
    failure that survives review.
    """
    a = MAN.get(asset_id)
    if not a or not a.get('material'):
        raise SystemExit(
            'manifest has no material %r — run geom.build_library and geom.derive_sapwood first' % asset_id
        )
    return a['material']['maps']


# ── materials ───────────────────────────────────────────────────────────────


def _img(path):
    im = bpy.data.images.load(path, check_existing=True)
    im.colorspace_settings.name = 'sRGB'
    return im


def _tex_node(nt, path, non_colour=False, projection='FLAT', scale=1.0, coord='UV'):
    n = nt.nodes.new('ShaderNodeTexImage')
    n.image = _img(path)
    if non_colour:
        n.image.colorspace_settings.name = 'Non-Color'
    n.projection = projection
    if projection == 'BOX':
        n.projection_blend = 0.35
    n.extension = 'REPEAT'

    tc = nt.nodes.new('ShaderNodeTexCoord')
    mp = nt.nodes.new('ShaderNodeMapping')
    mp.inputs['Scale'].default_value = (scale, scale, scale)
    nt.links.new(tc.outputs[coord], mp.inputs['Vector'])
    nt.links.new(mp.outputs['Vector'], n.inputs['Vector'])
    return n


def pbr_material(name, maps, tile_m, coord='UV', projection='FLAT'):
    """Principled BSDF wired from whatever maps the asset actually shipped."""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    bsdf = nt.nodes['Principled BSDF']
    scale = 1.0 / max(tile_m, 1e-6)

    if maps.get('diffuse'):
        n = _tex_node(nt, maps['diffuse'], False, projection, scale, coord)
        nt.links.new(n.outputs['Color'], bsdf.inputs['Base Color'])
    if maps.get('rough'):
        n = _tex_node(nt, maps['rough'], True, projection, scale, coord)
        nt.links.new(n.outputs['Color'], bsdf.inputs['Roughness'])
    else:
        bsdf.inputs['Roughness'].default_value = 0.88
    if maps.get('nor_gl'):
        n = _tex_node(nt, maps['nor_gl'], True, projection, scale, coord)
        nm = nt.nodes.new('ShaderNodeNormalMap')
        nm.inputs['Strength'].default_value = 1.0
        nt.links.new(n.outputs['Color'], nm.inputs['Color'])
        nt.links.new(nm.outputs['Normal'], bsdf.inputs['Normal'])
    if maps.get('ao'):
        # AO multiplied into base colour: cheap, and it keeps the fissures reading dark
        # even where the key light reaches into them.
        ao = _tex_node(nt, maps['ao'], True, projection, scale, coord)
        mix = nt.nodes.new('ShaderNodeMix')
        mix.data_type = 'RGBA'
        mix.blend_type = 'MULTIPLY'
        mix.inputs['Factor'].default_value = 0.65
        base = bsdf.inputs['Base Color']
        if base.is_linked:
            src = base.links[0].from_socket
            nt.links.new(src, mix.inputs[6])
            nt.links.new(ao.outputs['Color'], mix.inputs[7])
            nt.links.new(mix.outputs[2], base)
    return m


MAT_BARK = pbr_material('bark_oak', maps_for('bark_oak'), BARK_TILE_M, coord='UV')
# Cut interiors: object-space BOX projection at true scale — see the module docstring.
MAT_FRESH = pbr_material('cut_fresh', maps_for('wood_sapwood_fresh'), 0.30, coord='Object', projection='BOX')
MAT_WEATH = pbr_material('cut_weathered', maps_for('wood_scar_weathered'), 0.30, coord='Object', projection='BOX')


def _plain(name, rgb, rough=0.85, metallic=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes['Principled BSDF']
    b.inputs['Base Color'].default_value = (*rgb, 1.0)
    b.inputs['Roughness'].default_value = rough
    b.inputs['Metallic'].default_value = metallic
    return m


def _steel_material(name='steel'):
    """Forged, hand-worked steel: metallic, but never uniform.

    Flat grey with a single roughness value renders as cardboard — which is exactly how the
    first hurlbat read. Real forged plate has scale, pitting and polish wear, so roughness
    is driven by noise at two scales and the base colour darkens where it is roughest. That
    is the whole difference between "a metal object" and "a grey shape".
    """
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes['Principled BSDF']
    b.inputs['Metallic'].default_value = 1.0
    b.inputs['Base Color'].default_value = (0.44, 0.45, 0.47, 1.0)

    coarse = nt.nodes.new('ShaderNodeTexNoise')
    coarse.inputs['Scale'].default_value = 38.0
    coarse.inputs['Detail'].default_value = 6.0
    fine = nt.nodes.new('ShaderNodeTexNoise')
    fine.inputs['Scale'].default_value = 320.0
    fine.inputs['Detail'].default_value = 3.0
    mix = nt.nodes.new('ShaderNodeMix')
    mix.data_type = 'FLOAT'
    mix.inputs['Factor'].default_value = 0.4
    nt.links.new(coarse.outputs['Fac'], mix.inputs[2])
    nt.links.new(fine.outputs['Fac'], mix.inputs[3])

    rng = nt.nodes.new('ShaderNodeMapRange')
    rng.inputs['To Min'].default_value = 0.16  # burnished where it has been handled
    rng.inputs['To Max'].default_value = 0.44  # forge scale and pitting
    nt.links.new(mix.outputs[0], rng.inputs['Value'])
    nt.links.new(rng.outputs['Result'], b.inputs['Roughness'])

    # Dark. Under an overcast sky a bright metal mirrors a uniform white dome and comes
    # back as a pale flat shape — which is exactly how the first pass read. Fourteenth
    # century forged plate is dark grey-brown with scale on it, not polished stainless,
    # and the low values are what let the HDRI's highlights register as highlights.
    dark = nt.nodes.new('ShaderNodeMapRange')
    dark.inputs['To Min'].default_value = 0.34
    dark.inputs['To Max'].default_value = 0.16
    nt.links.new(mix.outputs[0], dark.inputs['Value'])
    ramp = nt.nodes.new('ShaderNodeCombineColor')
    for i in range(3):
        nt.links.new(dark.outputs['Result'], ramp.inputs[i])
    nt.links.new(ramp.outputs['Color'], b.inputs['Base Color'])

    # FORGE TEXTURE AS A BUMP, WHICH IS WHERE IT BELONGS. The plate's broad faces are
    # geometrically flat, so under an overcast dome every pixel on them reflects the same
    # patch of sky and the weapon renders as one value — measured at 19 luminance levels
    # out of 255, against 103 for the trunk. Displacing the mesh to fix that turned the
    # triangle fan into a visible pinwheel. A bump perturbs the shading normal per pixel
    # instead, so the reflected environment sweeps across the face and hammer texture
    # appears, with no topology to go wrong.
    bump = nt.nodes.new('ShaderNodeBump')
    bump.inputs['Strength'].default_value = 0.07
    bump.inputs['Distance'].default_value = 0.006
    nt.links.new(mix.outputs[0], bump.inputs['Height'])
    nt.links.new(bump.outputs['Normal'], b.inputs['Normal'])
    return m


MAT_STEEL = _steel_material()
# The haft is turned hickory, so it gets the photographed oak veneer rather than a flat
# brown — the rule applies to the axe as much as to the tree.
MAT_HAFT_WOOD = pbr_material('haft_wood', maps_for('wood_sapwood_fresh'), 0.22, coord='Object', projection='BOX')


# ── the trunk: a real displaced surface, not a normal-mapped cylinder ───────


def build_trunk():
    """Closed cylinder as an explicit UV grid, so UVs are exact and the mesh is manifold.

    Manifold matters: EXACT boolean on an open shell has no coherent inside, which is the
    same class of failure that made the first cut attempt subtract the whole trunk.
    """
    verts, faces, face_uvs = [], [], []
    circ = 2.0 * math.pi * TRUNK_R
    for j in range(NV + 1):
        z = -TRUNK_H / 2 + TRUNK_H * j / NV
        for i in range(NU):
            a = 2.0 * math.pi * i / NU
            verts.append((TRUNK_R * math.sin(a), TRUNK_R + TRUNK_R * math.cos(a), z))
    for j in range(NV):
        for i in range(NU):
            i2 = (i + 1) % NU
            a, b = j * NU + i, j * NU + i2
            c, d = (j + 1) * NU + i2, (j + 1) * NU + i
            faces.append((a, b, c, d))
            u0 = (i / NU) * circ / BARK_TILE_M
            u1 = ((i + 1) / NU) * circ / BARK_TILE_M
            v0 = (j / NV) * TRUNK_H / BARK_TILE_M
            v1 = ((j + 1) / NV) * TRUNK_H / BARK_TILE_M
            face_uvs.append([(u0, v0), (u1, v0), (u1, v1), (u0, v1)])

    # caps — never in frame, but they close the shell
    for j, sign in ((0, -1), (NV, 1)):
        cidx = len(verts)
        verts.append((0.0, TRUNK_R, -TRUNK_H / 2 if sign < 0 else TRUNK_H / 2))
        for i in range(NU):
            i2 = (i + 1) % NU
            a, b = j * NU + i, j * NU + i2
            faces.append((cidx, b, a) if sign < 0 else (cidx, a, b))
            face_uvs.append([(0.0, 0.0), (0.0, 0.0), (0.0, 0.0)])

    me = bpy.data.meshes.new('trunk')
    me.from_pydata(verts, [], faces)
    me.validate()
    me.update()
    uvl = me.uv_layers.new(name='UVMap').data
    for fi, poly in enumerate(me.polygons):
        for k in range(poly.loop_total):
            uvl[poly.loop_start + k].uv = face_uvs[fi][k]

    ob = bpy.data.objects.new('trunk', me)
    ob.data.materials.append(MAT_BARK)
    scene.collection.objects.link(ob)
    pass_lib.tag(ob, 'trunk')

    # real geometric displacement, before the booleans in the stack
    tex = bpy.data.textures.new('bark_disp', type='IMAGE')
    tex.image = _img(maps_for('bark_oak')['displacement'])
    tex.image.colorspace_settings.name = 'Non-Color'
    tex.extension = 'REPEAT'
    d = ob.modifiers.new('bark_displace', 'DISPLACE')
    d.texture = tex
    d.texture_coords = 'UV'
    d.uv_layer = 'UVMap'
    d.mid_level = 0.5
    d.strength = DISP_M
    return ob


trunk = build_trunk()


def _surface_y(u):
    return TRUNK_R - math.sqrt(max(TRUNK_R**2 - u**2, 1e-6))


def _gash(name, mat, length, width, depth, reach=None, segs=14, skew=0.45):
    """A hatchet gash: lenticular in the surface, V-shaped in section, deepest mid-length.

    THE BOX CUTTER WAS THE DEFECT. A rectangular solid subtracts a rectangular opening, and
    the first render of the spread cluster showed exactly that — flat black rectangles that
    read as stickers laid on the bark. No hatchet leaves a rectangle. A curved bit entering
    wood removes an almond: nothing at either end, widest and deepest in the middle.

    The V section is doing the other half of the work. Vertical box walls are parallel, so
    both catch the same light or neither does, and a deep box is simply a light trap that
    renders pure black. A V gives one lit wall and one shadowed wall, which is the contrast
    that reads as "chopped" rather than "painted".

    THE V IS ASYMMETRIC, AND THAT IS THE FIX FOR "SITS ON TOP". A symmetric V still read as
    an almond laid on the bark: both walls are equally steep, so both go equally dark and
    the shape has no interior gradient to say which way is down. A hatchet does not cut a
    symmetric slot — it drives in at an angle and levers a chip out, leaving one steep back
    wall and one long shallow ramp. `skew` offsets the apex toward the steep side, and the
    ramp that leaves is broad enough to catch the key and read as a lit floor descending
    into the wood. That gradient is what tells the eye the mark has depth.

    Local frame: +X along the strike, +Z across it, +Y into the wood. The solid starts
    `reach` OUTSIDE the surface so it still cuts wherever displacement has left a fissure.
    """
    reach = CUT_REACH if reach is None else reach
    verts, faces = [], []
    for i in range(segs + 1):
        s = i / segs
        e = math.sqrt(max(0.0, 1.0 - (2.0 * s - 1.0) ** 2))  # elliptical envelope
        e = max(e, 0.06)  # keep the end caps valid
        x = -length / 2 + length * s
        hw = (width / 2) * e
        dy = depth * e
        verts += [(x, -reach, -hw), (x, -reach, +hw), (x, dy, skew * hw)]
    for i in range(segs):
        a0, a1, a2 = 3 * i, 3 * i + 1, 3 * i + 2
        b0, b1, b2 = 3 * (i + 1), 3 * (i + 1) + 1, 3 * (i + 1) + 2
        faces += [(a0, b0, b1, a1), (a1, b1, b2, a2), (a2, b2, b0, a0)]
    faces += [(0, 1, 2), (3 * segs + 2, 3 * segs + 1, 3 * segs)]

    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.validate()
    me.update()
    ob = bpy.data.objects.new(name, me)
    ob.data.materials.append(mat)
    scene.collection.objects.link(ob)
    return ob


def _box(name, cx, cy, cz, sx, sy, sz, mat, rot_y=0.0, rot_z=0.0):
    hx, hy, hz = sx / 2, sy / 2, sz / 2
    v = [
        (-hx, -hy, -hz),
        (hx, -hy, -hz),
        (hx, hy, -hz),
        (-hx, hy, -hz),
        (-hx, -hy, hz),
        (hx, -hy, hz),
        (hx, hy, hz),
        (-hx, hy, hz),
    ]
    f = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    me = bpy.data.meshes.new(name)
    me.from_pydata(v, [], f)
    me.validate()
    me.update()
    ob = bpy.data.objects.new(name, me)
    ob.data.materials.append(mat)
    scene.collection.objects.link(ob)
    ob.rotation_euler = (0.0, math.radians(rot_y), math.radians(rot_z))
    ob.location = (cx, cy, cz)
    return ob


# ── the cut cluster ─────────────────────────────────────────────────────────
# EVERY MARK IS THIS WEAPON, SWEPT. Nothing below chooses a length, a width or a shape:
# each strike picks only which sharpened end hit, how hard, and how squarely, and
# hurlbat.strike_wound derives the cutter from the plate. The bit's curve is what makes the
# marks lenticular, and the 6mm plate is what sets their width — so no mark can be wider
# than the steel or longer than the edge that made it.
cuts, bools, strikes = [], [], []


def _wound(name, mat, element, depth, engage, place):
    v, f = hurlbat.strike_wound(element=element, depth=depth, engage=engage, reach=CUT_REACH)
    me = bpy.data.meshes.new(name)
    me.from_pydata(v, [], f)
    me.validate()
    me.update()
    ob = bpy.data.objects.new(name, me)
    ob.data.materials.append(mat)
    scene.collection.objects.link(ob)
    ob.matrix_world = place
    return ob


def _on_trunk(ux, vz, spin_deg):
    """Sit a wound on the trunk surface, turned by `spin_deg` in the image plane.

    The wound frame is +X along the chord, +Y into the wood, +Z across the kerf, so the
    strike angle is a rotation about Y — the axis pointing into the trunk.
    """
    return Matrix.Translation(Vector((ux, _surface_y(ux), vz))) @ Matrix.Rotation(math.radians(spin_deg), 4, 'Y')


ELEMENT_MIX = (['blade'] * 7) + ['beak', 'top_spike', 'butt_spike']

for i in range(N_CUTS):
    ang = random.uniform(0, math.tau)
    rad = CLUSTER_R * math.sqrt(random.uniform(0.10, 1.0))
    # centred on the impact point: these are earlier throws at the same target, so they
    # cluster around where he aims rather than around the trunk's centre line
    ux = max(-0.34, min(0.34, AXE_X + rad * math.cos(ang)))
    vz = AXE_Z + rad * math.sin(ang) * 0.85
    element = random.choice(ELEMENT_MIX)
    # a thrown weapon lands with whatever it lands with: some throws bury the bit, most
    # only catch it. Depth and engagement are the ONLY free parameters per strike.
    depth = random.uniform(0.004, 0.020)
    engage = random.uniform(0.28, 1.0) if element == 'blade' else random.uniform(0.5, 1.0)
    fresh = i % 4 == 0
    ob = _wound(
        'cut%d' % i,
        MAT_FRESH if fresh else MAT_WEATH,
        element,
        depth,
        engage,
        _on_trunk(ux, vz, random.uniform(-62, 62)),
    )
    cuts.append(ob)
    strikes.append(dict(hurlbat.wound_extent(element, depth, engage), at=[round(ux, 4), round(vz, 4)], fresh=fresh))

# THE WOUND THE HURLBAT IS SITTING IN. Without it the weapon meets unbroken bark and reads
# as stuck on rather than driven in — the same defect as the flat sprites, one level up.
# It is the same call as every other mark, at the same depth the weapon is seated.
AXE_ELEMENT = 'blade'
AXE_DEPTH = 0.030
entry = _wound(
    'cut_entry',
    MAT_FRESH,
    AXE_ELEMENT,
    AXE_DEPTH,
    1.0,
    _on_trunk(AXE_X, AXE_Z, 0.0) @ Matrix.Rotation(math.radians(26.0), 4, 'X'),
)
cuts.append(entry)
strikes.append(dict(hurlbat.wound_extent(AXE_ELEMENT, AXE_DEPTH, 1.0), at=[AXE_X, AXE_Z], fresh=True, seated=True))

for ob in cuts:
    bpy.context.view_layer.objects.active = ob
    ob.select_set(True)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.remove_doubles(threshold=1e-5)
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode='OBJECT')
    ob.select_set(False)
    ob.hide_render = True
    m = trunk.modifiers.new('scarcut_%s' % ob.name, 'BOOLEAN')
    m.operation = 'DIFFERENCE'
    m.object = ob
    m.solver = 'EXACT'
    m.material_mode = 'TRANSFER'  # the cut walls take the CUTTER's material
    bools.append(m)


def set_cuts(on):
    for m in bools:
        m.show_render = bool(on)
        m.show_viewport = bool(on)


def _evaluated_volume(ob):
    """Volume of the object AFTER its whole modifier stack — displace, then every cut."""
    dg = bpy.context.evaluated_depsgraph_get()
    ev = ob.evaluated_get(dg)
    me = ev.to_mesh()
    bm = bmesh.new()
    bm.from_mesh(me)
    v = bm.calc_volume()
    bm.free()
    ev.to_mesh_clear()
    return v


def seat_cuts(max_attempts=6):
    """Subtract the cuts, VERIFY the trunk survived, and re-jitter until it does.

    MEASURED, 2026-08-04: with the gash cutters the EXACT solver destroys the trunk at
    nu=160 but not at nu=128 or nu=224 — 72,362 trunk pixels became 2. Non-monotonic in
    resolution is the signature of a coplanarity edge case, not a modelling error: at that
    particular tessellation some cutter face lands exactly on a displaced trunk face and
    the solver's inside/outside test flips, so DIFFERENCE removes the volume it should have
    kept. The gash mesh itself is manifold, positively oriented, and subtracts correctly
    from a plain cylinder (verified in isolation).

    A silent version of this failure renders a perfectly plausible frame containing no
    tree, which is the worst possible outcome — it looks like a lighting problem and
    survives review. So the boolean is checked here rather than trusted: evaluate the whole
    stack, compare volume against the uncut trunk, and if the cuts removed more than they
    could possibly account for, nudge every cutter by a fraction of a millimetre to break
    the coplanarity and try again. Sub-millimetre jitter is invisible at any framing we
    shoot; a missing tree is not.
    """
    set_cuts(False)
    v_plain = _evaluated_volume(trunk)
    homes = [(tuple(c.location), tuple(c.rotation_euler)) for c in cuts]
    for attempt in range(max_attempts):
        set_cuts(True)
        v_cut = _evaluated_volume(trunk)
        removed = 1.0 - (v_cut / v_plain if v_plain else 0.0)
        # 24 gashes of at most 105x26x26mm cannot take even 1% of a 1.66 cubic metre trunk
        if 0.0 <= removed < 0.05:
            _zyg_log.info('BOOLEAN_OK attempt=%d removed=%.4f%% of trunk volume' % (attempt, removed * 100))
            return removed
        _zyg_log.info('BOOLEAN_BAD attempt=%d removed=%.2f%% — re-jittering cutters' % (attempt, removed * 100))
        rng = random.Random(SEED * 1000 + attempt)
        for c, (loc, rot) in zip(cuts, homes):
            c.location = tuple(v + rng.uniform(-4e-4, 4e-4) for v in loc)
            c.rotation_euler = tuple(v + rng.uniform(-0.004, 0.004) for v in rot)
        bpy.context.view_layer.update()
    raise SystemExit(
        'boolean failed after %d attempts — trunk volume dropped %.1f%%. '
        'Change --nu/--nv or --seed rather than shipping an empty frame.' % (max_attempts, removed * 100)
    )


seat_cuts()


# ── the hurlbat, seated in the wound it made ────────────────────────────────
# All steel, so one object and one material — there is no haft to separate.
weapon = hurlbat.build(MAT_STEEL, scene)
hurlbat.seat(
    [weapon],
    impact=(AXE_X, _surface_y(AXE_X), AXE_Z),
    element=AXE_ELEMENT,
    azimuth_deg=34.0,
    elevation_deg=-16.0,
    roll_deg=26.0,
    depth=AXE_DEPTH,
)
pass_lib.tag(weapon, 'axe_head')
axe = [weapon]

# ── ground ──────────────────────────────────────────────────────────────────
gm = bpy.data.meshes.new('ground')
gm.from_pydata(
    [(-6, -6, -TRUNK_H / 2), (6, -6, -TRUNK_H / 2), (6, 6, -TRUNK_H / 2), (-6, 6, -TRUNK_H / 2)], [], [(0, 1, 2, 3)]
)
gm.update()
ground = bpy.data.objects.new('ground', gm)
ground.data.materials.append(pbr_material('ground', maps_for('ground_forest'), 2.0, coord='Object', projection='BOX'))
scene.collection.objects.link(ground)
pass_lib.tag(ground, 'ground')

# ── light + camera ──────────────────────────────────────────────────────────
sun = bpy.data.lights.new('key', 'SUN')
sun.energy = 2.2
sun.angle = math.radians(9.0)
sun_ob = bpy.data.objects.new('key', sun)
sun_ob.rotation_euler = (math.radians(58), math.radians(-6), math.radians(38))
scene.collection.objects.link(sun_ob)
fill = bpy.data.lights.new('fill', 'SUN')
fill.energy = 0.55
fill_ob = bpy.data.objects.new('fill', fill)
fill_ob.rotation_euler = (math.radians(70), 0.0, math.radians(-135))
scene.collection.objects.link(fill_ob)

# IMAGE-BASED LIGHTING, NOT A FLAT COLOUR. The hurlbat is all steel, and a metal surface
# renders whatever surrounds it — against a flat-colour world it came back as grey
# cardboard however its material was set up. A CC0 overcast forest HDRI gives it something
# to reflect, and gives the wound interiors soft skylight so the V walls read as recessed
# instead of going to black.
world = bpy.data.worlds.new('w')
world.use_nodes = True
wnt = world.node_tree
bg = wnt.nodes['Background']
bg.inputs['Strength'].default_value = 1.0
_hdri = MAN.get('env_forest_overcast')
if _hdri:
    env = wnt.nodes.new('ShaderNodeTexEnvironment')
    env.image = bpy.data.images.load(_hdri['material']['maps']['hdri'], check_existing=True)
    wnt.links.new(env.outputs['Color'], bg.inputs['Color'])
else:
    bg.inputs['Color'].default_value = (0.35, 0.42, 0.36, 1)
scene.world = world

# NO KICKER. A reflection-vector area light was added here on the theory that flat metal
# under a uniform overcast dome has nothing to reflect. That theory was right about the
# physics and wrong about this bug: the hurlbat was rendering as crumpled cardboard because
# its broad faces were a TRIANGLE FAN centred outside its own concave outline, so half the
# triangles overlapped and wound backwards. With the faces properly tessellated the plate
# reads correctly under the HDRI alone, and the kicker only blew out the bark and burnt a
# white rim onto every ground edge. Fix the mesh, not the lighting.

cam_d = bpy.data.cameras.new('cam')
cam_d.lens = 62.0
cam = bpy.data.objects.new('cam', cam_d)
cam.location = (0.0, -1.55, 0.0)
cam.rotation_euler = (math.radians(90), 0.0, 0.0)
scene.collection.objects.link(cam)
scene.camera = cam

scene.render.engine = 'CYCLES'
scene.render.resolution_x = W
scene.render.resolution_y = H
scene.render.film_transparent = False
try:
    scene.cycles.device = 'CPU'
except AttributeError as _exc:
    _zyg_log.debug('cycles CPU device not set (no cycles settings on this scene): %s', _exc)


def emit(name, cuts_on, axe_on, host_on=True, samples=None):
    set_cuts(cuts_on)
    pass_lib.hide(axe, not axe_on)
    trunk.hide_render = not host_on
    ground.hide_render = not host_on
    d = pass_lib.render_set(name, OUT, scene=scene, samples=samples or SAMPLES)
    _zyg_log.info('TREE_SET %s -> %s' % (name, d))
    return d


# the hero plate, plus the two pairs the gate needs:
#   trunk_cut / trunk_plain   G3  — does the boolean relief reach the passes
#   hero      / axe_alone     G3b — how much of the blade the wood takes
emit('hero', True, not NO_AXE)
emit('trunk_cut', True, False)
emit('trunk_plain', False, False)
if not NO_AXE:
    emit('axe_alone', True, True, host_on=False)
    trunk.hide_render = False
    ground.hide_render = False

meta = {
    'nu': NU,
    'nv': NV,
    'cuts': N_CUTS,
    'seed': SEED,
    'trunk_r': TRUNK_R,
    'trunk_h': TRUNK_H,
    'bark_tile_m': BARK_TILE_M,
    'displacement_m': DISP_M,
    'cut_reach_m': CUT_REACH,
    'faces': NU * NV + 2 * NU,
    'materials': {
        'bark': 'bark_oak',
        'fresh': 'wood_sapwood_fresh',
        'weathered': 'wood_scar_weathered',
        'ground': 'ground_forest',
    },
    'pass_index': dict(pass_lib.IDX),
    # The weapon reports its OWN limits so the gate never carries a copy that can go
    # stale. It already did: gate_scene had the bit chord hard-coded at 108mm, the bit was
    # remodelled from the measured reference, and 32 marks were then flagged as longer
    # than a blade that no longer exists. The gate was right and the constant was wrong.
    'weapon': {
        'id': 'hurlbat',
        'plate_m': hurlbat.PLATE_M,
        'bevel_m': hurlbat.BEVEL_M,
        'elements': sorted(hurlbat.ELEMENTS),
        'element_chord_m': {
            k: round(max(math.dist(hurlbat.PROFILE[a], hurlbat.PROFILE[b]) for a in v for b in v), 5)
            for k, v in hurlbat.ELEMENTS.items()
        },
    },
    # every mark, with the strike that produced it — the marks are reproducible from this
    # alone, and the gate can check a measured wound against what the weapon can make
    'strikes': strikes,
}
with open(os.path.join(OUT, 'tree_meta.json'), 'w') as f:
    json.dump(meta, f, indent=1)
_zyg_log.info('TREE_BUILD_OK ' + json.dumps(meta))
