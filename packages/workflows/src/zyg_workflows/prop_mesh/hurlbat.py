# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""hurlbat.py — the hurlbat, and the wounds it makes. Blender-side (2026-08-04).

THE WEAPON
A hurlbat (whirlbat; England 1327 as "hurlebatte"; German wurfbeil) is a LATE-MEDIEVAL
ALL-STEEL THROWING AXE, sharpened on every auxiliary end to a point or a blade, cut from
plate around six millimetres thick. The arrangement of blades and spikes is the point of
the design: whichever way it arrives, something bites, so it can neither bounce nor slide.

In this production it is Cornelis van Haren's gift to his son Abel, and it recurs, so it is
registered as a manifest asset with its own licence-checked references rather than rebuilt
per scene.

Four cutting elements, every one of them sharp — this is what "sharpened on every auxiliary
end" means in geometry:
    blade       the axe bit: a bearded crescent flaring off the shaft
    beak        a pick spike opposite the blade
    top_spike   the shaft continued past the head to a point
    butt_spike  the other end of the shaft, also a point

THE WOUND IS NOT INVENTED — IT IS THE BLADE, SWEPT.
Every earlier version of the scars picked their length, width and depth from a random
range, which is guessing dressed as parameters. It is also wrong: this weapon has ONE
geometry, so the marks it leaves have one family of shapes. `strike_wound` derives the
cutter from the plate itself:

    length  the chord of the edge that actually entered — a full-face hit uses the whole
            bit, a glancing hit uses part of it, and nothing can produce a longer mark
            than the blade is long
    depth   how far the weapon travelled in, per strike
    width   NOT chosen. The kerf at the surface is the plate's own thickness where the
            surface plane crosses the bevel: 6mm at full depth, tapering to nothing at the
            edge. `w = PLATE_M * min(1, depth / BEVEL_M)`
    shape   falls out of the arc. Because the bit is curved, its middle penetrates deeper
            than its ends, so the mark is lenticular WITHOUT anyone deciding it should be.

So a shallow strike leaves a short, narrow, shallow mark and a committed one leaves a long,
6mm-wide, deep mark, and the two are the same weapon. Cut size is inferred, never guessed.

Profile traced against the CC0 references in data/assets/refs/ref_hurlbat — Met Museum axe
heads (3 views of one object) and 10th-15th century heads in the Novgorod, Ryazan, Smolensk
and Kirov museum collections, which give the bearded-bit flare and the socket-to-edge
proportion.
"""

import math

import bmesh
import bpy
from mathutils import Matrix, Vector
from mathutils.geometry import tessellate_polygon

PLATE_M = 0.006  # documented: hurlbats are cut from ~6mm steel plate
BEVEL_M = 0.016  # edge grind: distance behind the edge to reach full thickness
# The grind used for the MESH's bevel band is narrower than the one used for the kerf.
# BEVEL_M describes how thick the steel is at a given depth, which is what sets wound
# width; MESH_BEVEL_M is how wide the visible ground facet is. Driving the mesh from the
# 16mm figure put a 16mm facet on every edge of a ~100mm face, so a third of the weapon
# was bevel and it read as folded paper rather than as a plate with a ground edge.
MESH_BEVEL_M = 0.006

# ── the bit, MEASURED (2026-08-04) ───────────────────────────────────────────
# The first version of this profile was nineteen coordinates I wrote by hand after glancing
# at a contact sheet, while the docstring claimed they were traced from the references.
# They were not, and it showed: the bit came out 78x108mm — aspect 0.72, near-circular —
# which reads as a mallet head, and its throat was a STRAIGHT LINE. A crescent without a
# concave throat is not a crescent; it is a lollipop.
#
# These points are extracted, not drawn. Source: "Battle-axe blade (PSF)", public domain
# (Pearson Scott Foresman), in data/assets/refs/ref_hurlbat. The image was thresholded, the
# hatching morphologically closed, the outline flood-filled, and the bit's inner and outer
# boundaries read off per scanline. Measured:
#       aspect          0.577   (mine was 0.72; a bearded crescent is 0.45-0.60)
#       throat concavity 25.9%  of bit width (mine was 0.0%)
#       widest point    49% down the bit — a symmetric crescent
# Normalised so bit height = 1.0, origin at the deepest point of the throat, +X toward the
# cutting edge. Re-derivable from the same public file by the same steps.
#
# The DRAWING IS A POLEAXE, not a hurlbat, and only the bit crescent is taken from it. The
# shaft and the three spikes are constructed to the hurlbat's own documented description —
# all-steel plate, sharpened on every auxiliary end — because no photograph of one survives
# in any CC0 collection I could reach.
CRESCENT_OUTER = [
    (-0.1740, +0.5000),
    (-0.0734, +0.4725),
    (+0.0235, +0.4336),
    (+0.1160, +0.3856),
    (+0.2010, +0.3252),
    (+0.2810, +0.2583),
    (+0.3445, +0.1764),
    (+0.3808, +0.0796),
    (+0.3866, -0.0235),
    (+0.3615, -0.1238),
    (+0.3156, -0.2161),
    (+0.2443, -0.2918),
    (+0.1604, -0.3536),
    (+0.0715, -0.4078),
    (-0.0193, -0.4593),
    (-0.1160, -0.4978),
]
CRESCENT_INNER = [
    (-0.1871, +0.5000),
    (-0.1371, +0.4194),
    (-0.0754, +0.3424),
    (-0.0361, +0.2545),
    (-0.0370, +0.1555),
    (-0.0288, +0.0563),
    (-0.0207, -0.0429),
    (-0.0125, -0.1421),
    (-0.0001, -0.2398),
    (-0.0268, -0.3349),
    (-0.0754, -0.4211),
    (-0.1346, -0.4978),
]

BIT_H = 0.190  # bit height, metres — sets the scale of the measured crescent
SHAFT_HALF = 0.011  # half-width of the all-steel shaft
# Spikes shortened from 212/-196mm: at that length the top spike stood 117mm proud of a
# 190mm bit and the weapon read as a shuriken rather than an axe. A hurlbat's auxiliary
# points are there so it cannot land flat, not to out-reach the blade.
TOP_TIP = 0.156  # top spike tip, metres above origin
BUTT_TIP = -0.150  # butt spike tip
BEAK_TIP = -0.082  # how far the pick spike reaches behind the shaft


# The measured crescent is normalised with x=0 at the DEEPEST point of the throat, and its
# horns reach back 0.187 bit-heights from there. In the drawing the horns end level with the
# shaft's edge, so the crescent is placed by putting the horn line on the shaft edge; the
# throat then bulges 0.187*BIT_H to the right of it, which is what opens the two notches.
#
# HORN_GAP is not cosmetic. Placed flush, the inner horn tip lands EXACTLY on the shaft's
# edge line, so the outline touches itself there and stops being a simple polygon — which
# is precisely the ill-conditioned input that makes the boolean solver subtract the whole
# trunk. A real horn also stops short of the haft rather than kissing it, so 6mm of
# clearance is both correct and what keeps the mesh well formed.
HORN_GAP = 0.006
_OFF = SHAFT_HALF + HORN_GAP + 0.187 * BIT_H

# Which stretch of the throat is solid metal joining bit to shaft. Taken from the drawing's
# collar band (y 640..940 of a bit spanning 349..1263), normalised.
_ATTACH_HI, _ATTACH_LO = 0.182, -0.147


def _profile():
    """Weapon outline, built around the measured crescent.

    THE THROAT IS THE WHOLE POINT. Between each horn and the shaft there is OPEN SPACE — in
    the reference you can see background through it, above and below the collar. Omitting
    those two notches, as the first version did, fills the crescent in and turns it back
    into the lollipop this fix exists to remove. The bit therefore joins the shaft only
    across the collar band, and everywhere else the throat is a real gap.
    """
    s = BIT_H
    outer = [(x * s + _OFF, y * s) for x, y in CRESCENT_OUTER]
    inner = [(x * s + _OFF, y * s) for x, y in CRESCENT_INNER]
    hi = [p for p in inner if p[1] > _ATTACH_HI * s]  # upper throat, horn -> collar
    lo = [p for p in inner if p[1] < _ATTACH_LO * s]  # lower throat, collar -> horn
    neck_hi, neck_lo = hi[-1][1], lo[0][1]

    pts, elem = [], {}

    def add(seq, name=None):
        i0 = len(pts)
        pts.extend(seq)
        if name:
            elem[name] = list(range(i0, len(pts)))

    # Out across the neck, round the bit, back in. DIRECTION MATTERS: `hi` and `lo` are
    # both sliced from the throat top-to-bottom, so walking the outline needs them
    # reversed. Using `lo` as-sliced walks the lower throat upward and then jumps back
    # down to the bottom horn, which crossed the outline three times and would have handed
    # the boolean solver a non-simple polygon.
    add([(SHAFT_HALF, neck_hi)])  # neck top, on the shaft
    add(list(reversed(hi)))  # collar -> top horn
    add(outer, 'blade')  # the cutting edge
    add(list(reversed(lo)))  # bottom horn -> collar
    add([(SHAFT_HALF, neck_lo)])  # neck bottom, on the shaft
    add([(SHAFT_HALF, BUTT_TIP * 0.70), (0.0, BUTT_TIP), (-SHAFT_HALF, BUTT_TIP * 0.70)], 'butt_spike')
    add([(-SHAFT_HALF, -0.048)])
    add([(-SHAFT_HALF - 0.005, -0.026), (BEAK_TIP, 0.006), (-SHAFT_HALF - 0.005, 0.040)], 'beak')
    add([(-SHAFT_HALF, 0.064), (-SHAFT_HALF, TOP_TIP * 0.62)])
    add([(0.0, TOP_TIP), (SHAFT_HALF, TOP_TIP * 0.62)], 'top_spike')

    # counter-clockwise, so the extruded faces wind outward without relying on a repair
    area = 0.5 * sum(
        pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts))
    )
    if area < 0:
        n = len(pts)
        pts = pts[::-1]
        elem = {k: sorted((n - 1 - i) for i in v) for k, v in elem.items()}
    return pts, elem


PROFILE, ELEMENTS = _profile()


# ── the weapon ───────────────────────────────────────────────────────────────


def _thickness_at(pt, edge_pts):
    """Plate thickness at a point: ground away near a sharpened edge, full plate inboard."""
    d = min((Vector((pt[0], pt[1])) - Vector((e[0], e[1]))).length for e in edge_pts)
    return PLATE_M * min(1.0, d / BEVEL_M)


def _densify(pts, max_seg):
    """Insert points so no outline segment is longer than `max_seg`."""
    out = []
    n = len(pts)
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        out.append(a)
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        for k in range(1, int(L / max_seg)):
            f = k / max(int(L / max_seg), 1)
            out.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
    return out


def _inset(pts, dist):
    """Move every outline point inward along its bisector, clamped to the local width.

    A flat clamp would push the shoulder ring straight through itself in the throat
    notches, where the metal is only a few millimetres across. The inset at each point is
    therefore limited by the distance to the nearest NON-ADJACENT edge — a cheap local
    thickness — so narrow features keep a valid shoulder instead of turning inside out.
    """
    n = len(pts)
    out = []
    for i, p in enumerate(pts):
        a, b = pts[i - 1], pts[(i + 1) % n]
        nx, nz = 0.0, 0.0
        for u, v in ((a, p), (p, b)):
            dx, dz = v[0] - u[0], v[1] - u[1]
            L = math.hypot(dx, dz) or 1e-9
            nx += -dz / L  # inward for a counter-clockwise outline
            nz += dx / L
        L = math.hypot(nx, nz) or 1e-9
        nx, nz = nx / L, nz / L

        local = dist
        for j in range(n):
            if abs(j - i) <= 2 or abs(j - i) >= n - 2:
                continue
            q, r = pts[j], pts[(j + 1) % n]
            dx, dz = r[0] - q[0], r[1] - q[1]
            L2 = dx * dx + dz * dz or 1e-12
            t = max(0.0, min(1.0, ((p[0] - q[0]) * dx + (p[1] - q[1]) * dz) / L2))
            d = math.hypot(p[0] - (q[0] + t * dx), p[1] - (q[1] + t * dz))
            local = min(local, 0.40 * d)
        out.append((p[0] + nx * local, p[1] + nz * local))
    return out


def build(mat_steel, scene, name='hurlbat', seg_m=0.004):
    """The plate as a solid: two faces at +-thickness/2, joined by a rim band.

    Thickness varies per vertex, so every sharpened end really does come to an edge in the
    mesh rather than being a 6mm slab with a pointy silhouette.

    TWO REASONS THIS RENDERED AS CARDBOARD, BOTH FIXED HERE.

    1. THE RIM WAS 19 FACETS. Every bevel, every ground edge, the entire outline — 19 flat
       quads. `seg_m` now densifies the outline to ~4mm segments, so the rim becomes a
       smooth band that catches a bright skylight line along the ground edges. That
       highlight is most of what says "solid steel plate" rather than "paper cutout".

    2. THE FACES WERE PERFECTLY FLAT. Measured on the previous render, the weapon's surface
       normals varied by 5.3 degrees on average against the trunk's 33.8, and its luminance
       spanned 19 levels out of 255 against the trunk's 103. Under an overcast dome a flat
       face samples nearly the same radiance at every pixel, so it renders as one value —
       and roughness alone cannot rescue it, because a sharp and a blurry reflection of a
       UNIFORM sky are the same colour.

       THAT VARIATION BELONGS IN THE SHADER, NOT IN THE MESH. The first attempt displaced
       the face vertices by a sub-millimetre forge warp, and it made things worse in a new
       way: each broad face is a TRIANGLE FAN from a centre vertex, so warping the rim gave
       every one of the ~300 fan triangles its own normal and the weapon rendered as a
       pinwheel. The fan is the right topology for a flat plate and the warp is the wrong
       tool at this scale — a fraction of a millimetre of forge texture is shading detail,
       so it is a bump in the steel material instead. Structural shape stays geometry;
       surface texture stays shading.

    3. THE BEVEL RAN ALL THE WAY TO THE MIDDLE. With a single ring of rim vertices fanned
       to one centre point, thickness interpolates linearly from the edge to the centre —
       so what should be a 16mm grind became a 100mm cone, and every fan triangle sloped
       differently. That is what produced the pinwheel, and removing the warp did not fix
       it because the cause was the taper, not the warp. Real plate is FLAT with the grind
       confined to a band behind the edge, so the face is built as two rings: a shoulder
       ring at full thickness, inset behind the edge, fanned to the centre (all coplanar,
       one normal, no pinwheel), and a narrow bevel band from that shoulder out to the rim.
    """
    edge_pts = [PROFILE[i] for idxs in ELEMENTS.values() for i in idxs]
    prof = _densify(PROFILE, seg_m)
    n = len(prof)
    shoulder = _inset(prof, MESH_BEVEL_M)

    verts = []
    for sign in (-1.0, +1.0):
        for p in prof:  # 0..n-1 / n..2n-1  rim
            verts.append((p[0], sign * _thickness_at(p, edge_pts) / 2.0, p[1]))
    for sign in (-1.0, +1.0):
        for p in shoulder:  # 2n..3n-1 / 3n..4n-1  shoulder
            verts.append((p[0], sign * PLATE_M / 2.0, p[1]))
    faces = []
    for i in range(n):
        j = (i + 1) % n
        faces.append((2 * n + i, 2 * n + j, j, i))  # bevel band, front
        faces.append((3 * n + j, 3 * n + i, n + i, n + j))  # bevel band, back
        faces.append((i, j, n + j, n + i))  # the ground edge

    # THE FLAT FACES ARE PROPERLY TESSELLATED, NOT FANNED — this was the bug behind every
    # "crumpled paper" render. A fan needs a centre point INSIDE the polygon, and this
    # outline is deeply concave: a shaft with a crescent on one side, a beak on the other
    # and two open throat notches. The centroid of that lands in a notch, i.e. in fresh
    # air, so the fan triangles overlapped and half of them wound backwards. Rendered, that
    # is the black bowtie straight through the middle of the plate — which read as folds
    # and sent me chasing the material, the warp, the lighting and the bevel in turn.
    #
    # A single n-gon per side is no better: Blender's n-gon fill bridged straight across
    # the upper throat notch and the top spike, rendering them black. `tessellate_polygon`
    # is its own robust concave-polygon triangulator and is the tool for exactly this.
    tri = tessellate_polygon([[Vector((p[0], p[1], 0.0)) for p in shoulder]])
    for a, b_, c in tri:
        faces.append((2 * n + a, 2 * n + b_, 2 * n + c))  # flat face, front
        faces.append((3 * n + c, 3 * n + b_, 3 * n + a))  # flat face, back

    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.validate()
    me.update()

    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    me.update()
    ob = bpy.data.objects.new(name, me)
    ob.data.materials.append(mat_steel)
    scene.collection.objects.link(ob)
    # FLAT SHADING, DELIBERATELY. Smoothing plus an edge split blended the normal across
    # the 6mm bevel band and the plate came back looking like crumpled paper. Forged plate
    # with a ground edge really is a flat face meeting a crisp bevel, and that is what
    # reads as steel — the variation has to come from what it REFLECTS, not from bending
    # its normals.
    return ob


# ── the wound the weapon makes ───────────────────────────────────────────────


def _resample(points, n):
    """Even arc-length resampling of a polyline."""
    segs = [(Vector(a), Vector(b)) for a, b in zip(points, points[1:])]
    lens = [(b - a).length for a, b in segs]
    total = sum(lens) or 1e-9
    out = []
    for i in range(n):
        want = total * i / (n - 1)
        acc = 0.0
        for (a, b), L in zip(segs, lens):
            if acc + L >= want or (a, b) is segs[-1]:
                f = (want - acc) / max(L, 1e-9)
                out.append(a.lerp(b, min(max(f, 0.0), 1.0)))
                break
            acc += L
    return out


def strike_wound(element='blade', depth=0.014, engage=1.0, reach=0.030, stations=18, split_deg=30.0, chip_skew=0.5):
    """Cutter geometry for one strike, derived entirely from the weapon.

    element : which sharpened end hit
    depth   : how far the deepest point of that element travelled into the wood, metres
    engage  : 0-1, how much of the element's length was in contact. 1.0 is a square hit
              with the whole bit; a glancing blow engages a shorter chord and therefore
              leaves a shorter mark. Nothing here can produce a mark longer than the edge.
    reach   : how far the solid extends OUTSIDE the surface, so it still cuts through
              displaced bark
    split_deg : half-angle of the chip that splits out ahead of the wedge

    THE KERF IS NOT THE WOUND. The first version set the opening equal to the plate
    thickness, which is correct for the slot the steel occupies and wrong for the mark left
    behind: at 6mm on a 0.84m trunk that renders as a 7-pixel hairline, and the marks
    vanished. A wedge driven into wood does not part it cleanly — it splits a chip out
    ahead of itself, and the chip is far wider than the steel.

    That correction is still derived rather than chosen. The blade is a wedge; the wood
    fails along the grain at a roughly constant angle to the wedge face, so the chip
    released widens with penetration:

        mouth_half = kerf_half + depth * tan(split_deg)

    At 16mm deep with a 30-degree split that is 3 + 9 = 12mm a side, so a 24mm mark from
    6mm of steel — which is what axe marks in a trunk actually measure. The apex of the cut
    stays at the true kerf, because that part IS the steel. Deep strikes therefore open
    wide and shallow ones stay fine, from one weapon, with nothing to tune per mark.

    `chip_skew` biases the chip to one side. Wood splits toward the nearer free surface, so
    a real chip is lopsided, and that asymmetry is also what gives the mark a lit ramp on
    one wall and a shadowed face on the other instead of two matching dark walls.

    Returns (verts, faces) in the wound's own frame: +X along the chord, +Y into the wood,
    +Z across the kerf.
    """
    tan_split = math.tan(math.radians(split_deg))
    pts2 = [PROFILE[i] for i in ELEMENTS[element]]
    pts = _resample([(p[0], p[1]) for p in pts2], stations)

    # chord: from the first engaged point to the last. The strike direction is the outward
    # normal of that chord, so the deepest station is the one furthest along it.
    keep = max(2, int(round(stations * max(0.05, min(1.0, engage)))))
    lo = (stations - keep) // 2
    pts = pts[lo : lo + keep]

    a, b = pts[0], pts[-1]
    chord = b - a
    L = chord.length or 1e-9
    u = chord / L
    nrm = Vector((-u.y, u.x))
    if sum((p - a).dot(nrm) for p in pts) < 0:
        nrm = -nrm  # point it out of the metal

    proj = [(p - a).dot(nrm) for p in pts]
    deepest = max(proj) or 1e-9

    verts, faces = [], []
    for i, p in enumerate(pts):
        t = (p - a).dot(u)
        # this station entered by however much less than the deepest one it stands proud
        dy = depth - (deepest - proj[i])
        if dy <= 0.0:
            dy = 0.0005  # keep the sweep valid at the ends
        # KERF WIDTH IS THE PLATE, NOT A PARAMETER: the surface cuts the bevel at `dy`
        # behind the edge, so the steel is as thick there as the grind makes it.
        kerf_half = max(0.5 * PLATE_M * min(1.0, dy / BEVEL_M), 0.0004)
        # ...and the chip that splits out ahead of the wedge is wider than the steel.
        mouth_half = kerf_half + dy * tan_split
        off = chip_skew * dy * tan_split  # wood splits toward the free surface
        verts += [(t, -reach, -mouth_half + off), (t, -reach, +mouth_half + off), (t, dy, off * 0.35)]

    for i in range(len(pts) - 1):
        a0, a1, a2 = 3 * i, 3 * i + 1, 3 * i + 2
        b0, b1, b2 = 3 * (i + 1), 3 * (i + 1) + 1, 3 * (i + 1) + 2
        faces += [(a0, b0, b1, a1), (a1, b1, b2, a2), (a2, b2, b0, a0)]
    last = 3 * (len(pts) - 1)
    faces += [(0, 1, 2), (last + 2, last + 1, last)]
    return verts, faces


def wound_extent(element='blade', depth=0.014, engage=1.0, split_deg=30.0):
    """What the mark will measure, without building it — for the manifest and the gate."""
    pts2 = [PROFILE[i] for i in ELEMENTS[element]]
    pts = _resample([(p[0], p[1]) for p in pts2], 18)
    keep = max(2, int(round(18 * max(0.05, min(1.0, engage)))))
    lo = (18 - keep) // 2
    pts = pts[lo : lo + keep]
    kerf = PLATE_M * min(1.0, depth / BEVEL_M)
    return {
        'element': element,
        'length_m': round((pts[-1] - pts[0]).length, 5),
        'kerf_m': round(kerf, 5),  # the slot the steel occupies
        'width_m': round(kerf + 2 * depth * math.tan(math.radians(split_deg)), 5),
        'depth_m': round(depth, 5),
        'engage': round(engage, 4),
    }


def seat(objs, impact, element='blade', azimuth_deg=48.0, elevation_deg=-16.0, roll_deg=26.0, depth=0.030):
    """Place the weapon so `element` is buried `depth` into the surface at `impact`.

    Same construction as the wound: the strike direction is the element's outward normal,
    so the weapon and the mark it leaves are placed from one shared piece of geometry and
    cannot drift apart.
    """
    az, el = math.radians(azimuth_deg), math.radians(elevation_deg)
    d = Vector((math.sin(az), math.cos(az), math.sin(el))).normalized()
    up = Vector((0.0, 0.0, 1.0))
    if abs(d.dot(up)) > 0.98:
        up = Vector((0.0, 1.0, 0.0))
    edge = (up - d * up.dot(d)).normalized()
    bn = edge.cross(d)
    basis = Matrix((d, bn, edge)).transposed().to_4x4()

    # how far the element's tip stands from the plate origin, along its own outward normal
    pts2 = [PROFILE[i] for i in ELEMENTS[element]]
    tip = max(pts2, key=lambda p: p[0] ** 2 + p[1] ** 2)
    reachlen = math.hypot(tip[0], tip[1])
    # rotate the plate so the element points along +X (the strike), then back it off so
    # only `depth` is inside the wood
    ang = -math.atan2(tip[1], tip[0])
    spin = Matrix.Rotation(ang, 4, 'Y')
    back = Matrix.Translation(Vector((depth - reachlen, 0.0, 0.0)))
    m = Matrix.Translation(Vector(impact)) @ basis @ Matrix.Rotation(math.radians(roll_deg), 4, 'X') @ back @ spin
    for ob in objs:
        ob.matrix_world = m @ ob.matrix_world
    return m
