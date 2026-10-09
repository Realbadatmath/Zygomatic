# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""hatchet.py — the hatchet as real geometry, built to the CC0 reference (2026-08-04).

Imported by Blender scripts; needs bpy.

WHY THIS REPLACED TWO BOXES.
The first tree render put a grey rectangle and a tan rectangle in the trunk. In the decal
script that was defensible — the head was only ever a silhouette to composite — but as hero
geometry it reads as a cardboard hammer. The rules say every object gets a photoreal
reference and readable geometry, so the shape here is taken from the CC0 references in
data/assets/refs/ref_hatchet: a top-down photograph of a head buried in a log end, and two
line drawings of an axe standing in a stump.

WHAT THE REFERENCE ACTUALLY SHOWS
  * the head is a WEDGE in plan — thick at the poll, tapering to a cutting edge. That taper
    is the whole reason it looks like it can bite; a constant-thickness slab never will.
  * in profile the outline is not a rectangle: a squared poll, a waisted neck, then a bit
    that FLARES top and bottom before curving to the edge.
  * the haft is oval in section with its long axis in the blade plane, tapers toward the
    middle and swells again at the knob.

THE ORIENTATION PROBLEM, AND WHY THE STRIKE IS OBLIQUE.
An axe driven horizontally into a vertical trunk and viewed head-on is ALWAYS seen edge-on.
That is not a modelling choice, it is geometry: the blade's normal is perpendicular to the
penetration direction, penetration runs along the view axis, so the normal is perpendicular
to the view and the head presents its thickness. The reference drawings show broad faces
because they are STUMPS — a horizontal cut face viewed from the side.

Trying to fix that by rotating the head into the camera would have it entering the wood
broad-face-first, which no axe does. The honest fix is to change the STRIKE, not the head:
it lands obliquely, off the trunk's centre line where the surface already turns away. At
55 degrees of azimuth the blade normal picks up a large component toward the camera, so
most of the broad face is visible while the bit still travels into the wood along its own
edge. Thrown axes land obliquely far more often than square, so this costs nothing in
plausibility and buys the entire read.
"""

import math

import bpy
from mathutils import Matrix, Vector

# Head profile in the blade plane: +X from poll toward the cutting edge, +Z up, Y is
# thickness. Metres. Traced from the CC0 top-down reference.
HEAD_PROFILE = [
    (-0.052, -0.028),
    (-0.052, 0.028),
    (-0.020, 0.030),
    (0.012, 0.026),
    (0.040, 0.044),
    (0.060, 0.036),
    (0.068, 0.014),
    (0.070, 0.000),
    (0.068, -0.014),
    (0.060, -0.036),
    (0.040, -0.044),
    (0.012, -0.026),
    (-0.020, -0.030),
]

# Thickness at a given X. The near-zero final value IS the cutting edge.
HEAD_THICKNESS = [(-0.052, 0.028), (0.012, 0.026), (0.040, 0.016), (0.060, 0.006), (0.070, 0.0015)]

HAFT_LEN = 0.300
HAFT_DROOP = 0.052  # how far the knob falls below the eye, metres


def _thickness(x):
    pts = HEAD_THICKNESS
    if x <= pts[0][0]:
        return pts[0][1]
    for (x0, t0), (x1, t1) in zip(pts, pts[1:]):
        if x <= x1:
            f = (x - x0) / max(x1 - x0, 1e-9)
            return t0 + (t1 - t0) * f
    return pts[-1][1]


def _mesh(name, verts, faces, mat, scene):
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.validate()
    me.update()
    ob = bpy.data.objects.new(name, me)
    ob.data.materials.append(mat)
    scene.collection.objects.link(ob)
    return ob


def build_head(mat, scene, name='axe_head'):
    """Two broad faces joined by a rim band; thickness varies along X, so it is a wedge."""
    n = len(HEAD_PROFILE)
    front, back = [], []
    for x, z in HEAD_PROFILE:
        h = _thickness(x) / 2.0
        front.append((x, -h, z))
        back.append((x, +h, z))
    verts = front + back
    cf, cb = len(verts), len(verts) + 1
    verts.append((sum(p[0] for p in front) / n, -0.004, 0.0))
    verts.append((sum(p[0] for p in back) / n, +0.004, 0.0))

    faces = []
    for i in range(n):
        j = (i + 1) % n
        faces.append((cf, j, i))  # front fan
        faces.append((cb, n + i, n + j))  # back fan
        faces.append((i, j, n + j, n + i))  # rim
    return _mesh(name, verts, faces, mat, scene)


def build_haft(mat, scene, name='axe_haft', segments=18, sides=12):
    """Oval section swept along a drooping line, waisted in the middle, knob at the end.

    The long axis of the oval lies in the blade plane, which is what stops a haft reading
    as a dowel.
    """
    verts, faces = [], []
    for s in range(segments + 1):
        f = s / segments
        x = -0.010 - HAFT_LEN * f
        z = -HAFT_DROOP * (f**1.6)
        # taper to a waist at ~60% then swell into the knob
        w = 1.0 - 0.22 * math.sin(math.pi * min(f / 0.75, 1.0)) + 0.18 * max(0.0, f - 0.88) / 0.12
        a, b = 0.0165 * w, 0.0245 * w  # a across the blade, b in the blade plane
        for k in range(sides):
            t = 2 * math.pi * k / sides
            verts.append((x, a * math.sin(t), z + b * math.cos(t)))
    for s in range(segments):
        for k in range(sides):
            k2 = (k + 1) % sides
            a0 = s * sides + k
            b0 = s * sides + k2
            faces.append((a0, b0, (s + 1) * sides + k2, (s + 1) * sides + k))
    # cap both ends
    c0, c1 = len(verts), len(verts) + 1
    verts.append((-0.010, 0.0, 0.0))
    verts.append((-0.010 - HAFT_LEN, 0.0, -HAFT_DROOP))
    for k in range(sides):
        k2 = (k + 1) % sides
        faces.append((c0, k2, k))
        faces.append((c1, segments * sides + k, segments * sides + k2))
    ob = _mesh(name, verts, faces, mat, scene)
    # a turned haft is a smooth solid of revolution; flat shading made it read as a
    # 12-sided pencil. The head stays flat-shaded — a forged head really does have facets.
    for p in ob.data.polygons:
        p.use_smooth = True
    return ob


def seat(objs, impact, azimuth_deg=55.0, elevation_deg=-14.0, roll_deg=22.0, insert_m=0.030):
    """Place the hatchet so its bit travels into the wood along its own edge.

    impact       : world point where the edge meets the surface
    azimuth_deg  : how far the strike is turned off the camera axis. 0 would drive the head
                   straight away from the viewer and show only its thickness.
    elevation_deg: downward component of the strike
    roll_deg     : rotation about the strike axis — tips the cutting edge off vertical
    insert_m     : how deep the bit sits in the wood. Without this the head is placed with
                   its ORIGIN at the surface, which buries all 70mm from origin to cutting
                   edge and leaves nothing to see. A thrown hatchet bites 20-35mm.
    """
    az, el = math.radians(azimuth_deg), math.radians(elevation_deg)
    d = Vector((math.sin(az), math.cos(az), math.sin(el))).normalized()  # penetration, +X
    up = Vector((0.0, 0.0, 1.0))
    if abs(d.dot(up)) > 0.98:
        up = Vector((0.0, 1.0, 0.0))
    z_axis = (up - d * up.dot(d)).normalized()  # along the cutting edge, +Z
    y_axis = z_axis.cross(d)  # blade normal, +Y
    basis = Matrix((d, y_axis, z_axis)).transposed().to_4x4()
    edge_x = max(p[0] for p in HEAD_PROFILE)
    back_off = Matrix.Translation(Vector((insert_m - edge_x, 0.0, 0.0)))
    m = Matrix.Translation(Vector(impact)) @ basis @ Matrix.Rotation(math.radians(roll_deg), 4, 'X') @ back_off
    for ob in objs:
        ob.matrix_world = m @ ob.matrix_world
    return m


def build(mat_steel, mat_wood, scene, impact, **kw):
    head = build_head(mat_steel, scene)
    haft = build_haft(mat_wood, scene)
    seat([head, haft], impact, **kw)
    return head, haft


def entry_gash(insert_m=0.030, azimuth_deg=55.0, elevation_deg=-14.0, roll_deg=22.0):
    """Dimensions of the gash THIS hatchet would leave, for the cutter that makes it.

    Returned rather than hard-coded so the wound and the blade cannot drift apart: the gash
    is as long as the bit is tall and as deep as the bit is inserted.
    """
    bit_h = max(abs(z) for _, z in HEAD_PROFILE) * 2.0
    return {
        'length': bit_h * 0.92,
        'width': 0.026,
        'depth': insert_m,
        'azimuth_deg': azimuth_deg,
        'elevation_deg': elevation_deg,
        'roll_deg': roll_deg,
    }
