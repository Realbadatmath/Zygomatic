# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""pufferball.geometry — the primitive builders the parts are assembled from.

Verbatim sections of the original pufferball.py (lines 223-515): the helpers, the
face-datum maths (_face_centre_y / _face_surface_y), the sphere / capsule / UV
primitives and the fur, bald-patch and hair particle systems.
"""

from .constants import IDX, P, Vector, _zyg_log, bmesh, bpy, math


# ── helpers ──────────────────────────────────────────────────────────────────


def _link(ob, scene):
    scene.collection.objects.link(ob)
    return ob


# ── where the face actually IS ───────────────────────────────────────────────
# Two separate bugs came from one habit: measuring a feature from the face CENTRE
# while the parameter was written to mean the face SURFACE. The face is an
# ellipsoid with a Y half-axis of face_r * 0.62, so the two datums are 69 mm apart
# on axis and further off it. The mouth ended up 42 mm inside the head and
# invisible in all 16 sheet views; `eye_out=26mm` delivered 10.8 mm. Anything that
# must SIT ON the face measures from _face_surface_y, never from _face_centre_y.


def _sagitta(r, rings):
    """How far a tessellated sphere of radius `r` falls INSIDE the true sphere.

    Two nearly-tangent surfaces cannot be separated by less than the sum of their
    sagittas or they interleave and z-fight. This is the floor on how flush a
    detail sphere (pupil, and anything like it) may sit against its host."""
    return r * (1.0 - math.cos(math.pi / max(rings, 2)))


def _face_centre_y(p=P):
    """Y of the face ellipsoid's CENTRE."""
    return -(p['body_ry'] - p['face_r'] * 0.42) - p['face_bulge']


def _face_surface_y(x, z, p=P):
    """Y of the face ellipsoid's front surface directly in front of (x, z).

    Returns None when (x, z) falls outside the face's silhouette, so a caller that
    places a feature off the patch fails loudly instead of quietly landing it in
    open air."""
    cy = _face_centre_y(p)
    cz = p['body_lift'] + p['face_z']
    r = p['face_r']
    t = (x / r) ** 2 + ((z - cz) / r) ** 2
    if t >= 1.0:
        return None
    return cy - r * 0.62 * math.sqrt(1.0 - t)


def _outward(me):
    """Make every face normal point out of the volume.

    Winding is easy to get wrong by hand and CYCLES CANNOT SHOW YOU: it flips the
    shading normal toward the incoming ray, so an inside-out mesh renders perfectly
    and only breaks later — in a backface-culling viewer, a normal bake, a boolean.
    14 of the 39 parts shipped inverted (both arms, all 6 fingers, all 6 toes)
    because _capsule's side-wall winding is the mirror of _sphere's, and 16 beauty
    renders looked correct the whole time. Recalculating is construction-order
    independent, so no future primitive can reintroduce it."""
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()


def _cylindrical_uv(me):
    """Per-loop UVs from each vertex's angle about local Z.

    Every primitive here is a surface of revolution about its own Z, so the
    parameterisation is analytic — no unwrap, no seam to place by hand, and it
    costs nothing at build time. Without UVs the creature cannot carry a texture
    at all, which blocks the speckled skin the reference has.

    The wrap seam is fixed PER FACE: a face straddling u=0 gets its low corners
    pushed to u+1 rather than spanning the whole map backwards. Verts on the axis
    (the sphere's poles, the capsule's caps) have no angle of their own and take
    the mean of the face's other corners, which pinches the pole the way any UV
    sphere does."""
    uvl = me.uv_layers.new(name='UVMap')
    co = [v.co.copy() for v in me.vertices]
    zs = [c.z for c in co]
    z0, z1 = min(zs), max(zs)
    dz = (z1 - z0) or 1.0
    for poly in me.polygons:
        loops = list(poly.loop_indices)
        us, vs, axial = [], [], []
        for li in loops:
            c = co[me.loops[li].vertex_index]
            on_axis = (c.x * c.x + c.y * c.y) < 1e-12
            axial.append(on_axis)
            us.append(0.0 if on_axis else (math.atan2(c.y, c.x) / (2.0 * math.pi)) % 1.0)
            vs.append((c.z - z0) / dz)
        real = [u for u, a in zip(us, axial) if not a]
        if real and (max(real) - min(real)) > 0.5:
            us = [u + 1.0 if (u < 0.5 and not a) else u for u, a in zip(us, axial)]
            real = [u for u, a in zip(us, axial) if not a]
        if real:
            mean_u = sum(real) / len(real)
            us = [mean_u if a else u for u, a in zip(us, axial)]
        for k, li in enumerate(loops):
            uvl.data[li].uv = (us[k], vs[k])
    return uvl


def _sphere(name, loc, radius, scene, mat, segs=32, rings=16, idx='body'):
    """A UV sphere as its own object. `radius` is a float or an (rx, ry, rz) triple.

    THE RADII ARE BAKED INTO THE VERTICES, never applied as object scale. A DISPLACE
    modifier works in LOCAL space, so on a unit sphere scaled to 0.15 a 16 mm fur
    displacement renders as 16 mm x 0.15 = 2.4 mm — invisible, which is exactly how
    the first preview came back a smooth white balloon with no fur at all. Baking
    the radius keeps object scale at 1.0 and the modifier honest."""
    me = bpy.data.meshes.new(name)
    bm_verts, bm_faces = _uv_sphere_data(radius, segs, rings)
    me.from_pydata(bm_verts, [], bm_faces)
    me.validate()
    _cylindrical_uv(me)
    _outward(me)
    for poly in me.polygons:
        poly.use_smooth = True
    ob = bpy.data.objects.new(name, me)
    ob.location = loc
    ob.data.materials.append(mat)
    ob.pass_index = IDX[idx]
    return _link(ob, scene)


def _uv_sphere_data(radius, segs, rings):
    """verts/faces for a UV sphere. Poles are single verts (triangles at the caps,
    quads between), which is what Blender's own primitive produces."""
    rx, ry, rz = (radius, radius, radius) if isinstance(radius, (int, float)) else radius
    verts = [(0.0, 0.0, rz)]
    for i in range(1, rings):
        phi = math.pi * i / rings
        cz, sr = math.cos(phi), math.sin(phi)
        for j in range(segs):
            th = 2.0 * math.pi * j / segs
            verts.append((rx * sr * math.cos(th), ry * sr * math.sin(th), rz * cz))
    verts.append((0.0, 0.0, -rz))
    faces = []
    for j in range(segs):
        faces.append((0, 1 + j, 1 + (j + 1) % segs))
    for i in range(rings - 2):
        a, b = 1 + i * segs, 1 + (i + 1) * segs
        for j in range(segs):
            j2 = (j + 1) % segs
            faces.append((a + j, b + j, b + j2, a + j2))
    last = len(verts) - 1
    base = 1 + (rings - 2) * segs
    for j in range(segs):
        faces.append((last, base + (j + 1) % segs, base + j))
    return verts, faces


def _capsule(name, p0, p1, r0, r1, scene, mat, sides=14, idx='arm'):
    """A tapered capsule from p0 to p1 — the limb/toe primitive. Built directly so
    the two end radii can differ, which a scaled cylinder cannot do."""
    p0, p1 = Vector(p0), Vector(p1)
    axis = p1 - p0
    length = axis.length
    if length < 1e-6:
        raise ValueError('%s: zero-length capsule' % name)
    quat = axis.normalized().to_track_quat('Z', 'Y')
    verts, faces = [], []
    for _ring, (z, rr) in enumerate(((0.0, r0), (length, r1))):
        for j in range(sides):
            th = 2.0 * math.pi * j / sides
            verts.append((rr * math.cos(th), rr * math.sin(th), z))
    for j in range(sides):
        j2 = (j + 1) % sides
        faces.append((j, sides + j, sides + j2, j2))
    # rounded caps: one vert each, so a finger tip is domed not flat
    verts.append((0.0, 0.0, -r0 * 0.85))
    verts.append((0.0, 0.0, length + r1 * 0.85))
    c0, c1 = len(verts) - 2, len(verts) - 1
    for j in range(sides):
        j2 = (j + 1) % sides
        faces.append((c0, j2, j))
        faces.append((c1, sides + j, sides + j2))
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.validate()
    _cylindrical_uv(me)
    _outward(me)
    for poly in me.polygons:
        poly.use_smooth = True
    ob = bpy.data.objects.new(name, me)
    ob.location = p0
    ob.rotation_mode = 'QUATERNION'
    ob.rotation_quaternion = quat
    ob.data.materials.append(mat)
    ob.pass_index = IDX[idx]
    return _link(ob, scene)


def _subsurf(ob, levels=2):
    m = ob.modifiers.new('subsurf', 'SUBSURF')
    m.levels = m.render_levels = levels
    return m


def _fur(ob, amplitude, scale):
    """Crinkle the SURFACE so the shading is not glassy.

    `scale` is a feature COUNT across the object, converted to Blender's noise_scale
    (which is a feature SIZE in local units, so smaller = higher frequency). The
    first pass passed 1/9 straight through as noise_scale, giving features a third
    of the body wide — that is a lumpy potato, not fur, and at mid_level 0.42 on a
    clouds texture averaging ~0.5 the mean displacement was 1.6 mm anyway.

    This is surface only. The silhouette is `_hair`'s job — displacement can never
    produce a spiky outline, because it moves a closed surface rather than growing
    strands off it."""
    size = max(ob.dimensions) if max(ob.dimensions) > 0 else 0.3
    tex = bpy.data.textures.new(ob.name + '_fur', 'CLOUDS')
    tex.noise_scale = size / max(scale, 1.0)
    tex.noise_depth = 4
    tex.noise_basis = 'BLENDER_ORIGINAL'
    m = ob.modifiers.new('fur', 'DISPLACE')
    m.texture = tex
    m.strength = amplitude
    m.mid_level = 0.5
    m.texture_coords = 'LOCAL'
    return m


def _bald_patch(ob, centre, radius, name='fur_density'):
    """Vertex group that is 0 over a spherical region and 1 elsewhere.

    Fed to the particle system as `vertex_group_density`. Without it the body hair
    grows straight over the face and the first fluffy render buried both eyes, the
    mouth and the whole turquoise patch under white strands — the creature became
    an anonymous ball of fluff. Fur that hides the identity is worse than no fur."""
    vg = ob.vertex_groups.new(name=name)
    c = Vector(centre)
    for v in ob.data.vertices:
        d = (Vector(v.co) - c).length
        # 1 outside, feathered to 0 inside, so the hairline is soft not cut
        w = 0.0 if d < radius * 0.72 else min(1.0, (d - radius * 0.72) / (radius * 0.45))
        vg.add([v.index], w, 'REPLACE')
    return vg


def _hair(ob, length, count=1500, children=8, seed=0, thick=0.0018, density_group=None):
    """Grow fur strands. THIS is what makes the outline read as a creature.

    Silhouette survives downscaling; surface texture does not. At the size the
    pufferball occupies in a training tile, the spiky outline is most of the
    identity — a smooth ball reads as a balloon no matter how good the shader is.

    Kept cheap deliberately: a few thousand parents with interpolated children,
    3 hair steps, and no dynamics. The strands only have to break the edge."""
    bpy.context.view_layer.objects.active = ob
    ob.modifiers.new('hair', 'PARTICLE_SYSTEM')
    ps = ob.particle_systems[-1]
    ps.seed = seed
    s = ps.settings
    s.type = 'HAIR'
    s.count = count
    s.hair_length = length
    s.hair_step = 3
    s.use_advanced_hair = True
    s.child_type = 'INTERPOLATED'
    s.child_percent = children
    s.rendered_child_count = children
    s.child_length = 1.0
    s.child_radius = 0.012
    # ROUGHNESS IS IN OBJECT UNITS (metres), NOT a fraction of strand length. This
    # is the single most expensive misreading in this file: roughness_1=0.10 on a
    # 13 mm hair displaces keys by 100 mm, and the render came back as a 650 mm
    # ball of straw. Measured proof it was not length: sweeping hair_len 3→16 mm
    # moved the rendered halo by 8 mm (164→172), because the halo was roughness
    # the whole time. Scale both off `length` so they stay sane at any size.
    s.roughness_1 = length * 0.18  # per-strand kink — "spiky", not "combed"
    s.roughness_1_size = length * 0.60
    s.roughness_endpoint = length * 0.30
    s.brownian_factor = 0.0
    s.render_type = 'PATH'
    if density_group:
        ps.vertex_group_density = density_group
    # Strand thickness: root slightly thicker than tip, both very fine.
    # Blender's strand radius is root_radius * radius_scale, and the DEFAULTS are
    # root_radius=1.0 / radius_scale=0.01 tuned for a 4 m default hair. Pinning
    # radius_scale to 1.0 makes `thick` mean plain metres, which is the only way
    # this stays readable — but it also means `thick` must be a believable hair
    # radius. 1.6 mm is rope; real fur here is ~0.2 mm.
    try:
        s.radius_scale = 1.0
        s.root_radius = thick
        s.tip_radius = thick * 0.30
    except AttributeError as _exc:
        _zyg_log.debug('hair radius attributes unavailable on this blender build: %s', _exc)
    return ps
