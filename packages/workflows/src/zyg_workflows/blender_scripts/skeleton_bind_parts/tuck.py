# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The tuck: no trunk bone may stand outside the skin it lives in."""

import math

import bpy
from mathutils import Vector

# --------------------------------------------------------------------------
# the tuck: no trunk bone may stand outside the skin it lives in
# --------------------------------------------------------------------------
#
# The trunk is placed as ONE rigid block scaled by STANDING HEIGHT, so nothing
# in that placement can match this body's DEPTH.  On male_realistic the block's
# least-squares slide left the sternum and the medial rib ends 12.7 mm in front
# of the chest skin (152 ribcage vertices outside it, plus 28 on each clavicle),
# and the T5-T9 spinous processes out through the back -- bone drawn over the
# muscle layer, which rides only 1.5 mm under that skin, so the operator saw the
# ribs come through the chest on a walk (2026-09-24).  No further slide can fix
# that: the block is already balanced, and what is wrong is that this skeleton's
# thorax does not have this body's cross-section, front and back at once.
#
# So the trunk is fitted to the skin's own DEPTH, by height:
#
#     y' = yc + a(z) * (y - yc) + d(z)
#
# a and d piecewise linear in height over TUCK_BAND bands, each band's pair
# solved so that every vertex in it sits between the front and the back of the
# skin in its own 2 cm cell (``_silhouette_columns``) with TUCK_MARGIN of soft
# tissue to spare, the least squeeze and the smallest slide that will do.
#
# WIDTH WAS TRIED AND THROWN OUT, and the reason is worth keeping: the same
# field over min/max x per (y, z) cell reads the lateral end of a rib 85 mm
# "outside" and squeezes the thorax into the 10 % floor without clearing
# anything. A (y, z) cell is a 2 cm slab of DEPTH, and the frontmost slab of a
# chest is only as wide as the sternum, so every lateral structure at that
# depth is "outside" it. Front-to-back is a silhouette a cell can state;
# side-to-side, at that cell size, is not.
#
# ONE FIELD OVER THE WHOLE TRUNK, not a transform per piece or per group,
# because a joint is two bones at the same height: give the ribcage and the
# vertebrae it articulates with their own best-fit transforms and they come
# apart by a centimetre (measured), and a per-group solve steps the spine at
# every group boundary (C7/T1, T6/T7, T12/L1).  A field that depends only on
# height moves everything at that height together, so the column stays a
# column, the girdle stays on the thorax, and only what is actually wrong is
# corrected: the pelvis, which fits, keeps a = 1 and d = 0.
#
# The skull is its own field for the same anatomical reason -- it is the head,
# not the trunk -- so a chest squeeze cannot pull the face bones off the face.
#
# Limb tips are NOT tucked. The fingers', toes' and heel bones also stand
# outside the skin (19-28 mm), but there the cause is the axis fit of the group
# (STUB_GROUPS, and the Foot's 1.093 axis scale), not a cross-section mismatch,
# and no field over a body's silhouette will cure it. It is a separate defect,
# and it was there before this pass existed.
#
# WHAT THE TUCK CANNOT SEE. A silhouette is two numbers per cell, so a bone
# that leaves the skin where the surface faces neither along the axis nor
# across it -- the top of the shoulder, the crest of the ilium -- is invisible
# to it, and so is anything in a cell whose skin is thinner than min_span. The
# nearest-surface test in ``_surface_depth`` sees those, and lies in every
# concavity instead (39 % of the skull "outside" through the mouth bag, the
# femoral neck through the crotch cleft), which is why the fit is measured with
# both and neither is trusted alone. What the operator sees is the check that
# settles it, and after this pass the chest reads clean.

TUCK_UNITS = (
    ('trunk', ('Hips', 'LowerBack', 'Spine', 'Spine1', 'Neck', 'Neck1', 'LeftShoulder', 'RightShoulder')),
    ('head', ('Head',)),
)
TUCK_MARGIN = 0.005  # 5 mm of soft tissue wanted over every band
TUCK_MIN_CLEAR = 0.0015  # 1.5 mm is the pass mark: the écorché's own inset
TUCK_PASSES = 3  # the field is piecewise linear, so it converges
# A squeeze this deep is a real reshape, and for the female body it is the
# honest answer: ONE CC0 skeleton serves both bodies, and at 1.641 m its male
# thorax is 24 mm deeper than that chest (measured), which no slide can absorb.
# Bones outside the skin is the worse of the two answers, and the solver takes
# the LEAST squeeze that clears the skin, so this floor only ever binds where
# the mismatch is real: the male body's worst band stops at 0.926.
TUCK_SCALE_FLOOR = 0.80
TUCK_STEPS = 51  # a resolution of 0.2 % on `a`
TUCK_BAND = 0.04  # metres of height per band
TUCK_STRIDE = 2

# THE LAST LINE, and why the field is not enough on its own. A silhouette cell
# states front and back, so the field cannot reach a bone that leaves the skin
# sideways: after it had cleared the sternum, the lateral ends of ribs 6-9 still
# showed through the écorché (2 mm by the nearest-surface test, and two white
# slivers on the plate). And the COLLAPSE decimate runs after it on the joined
# mesh, where it is free to merge a clavicle vertex into a scapula one 20 mm
# away -- containment fitted before that is containment the decimate may spend.
# So the shipped mesh gets one local pass: every vertex the body's own BVHTree
# calls outside is pushed back along the SKIN's normal, at most TUCK_PUSH_MAX,
# with a skirt over its one-ring so a tucked tip stays smooth.
#
# NOT ON THE SKULL. ``_surface_depth``'s test reads 40 % of the cranium as
# outside through the open mouth bag, and pushing 6800 skull vertices along
# those normals would take the face apart. The head keeps the field, which is
# measured against a silhouette and cannot be fooled that way.
TUCK_PUSH_UNITS = ('trunk',)
# 10 mm, because the female body needs it: one CC0 skeleton for both bodies
# leaves its T7-T12 spinous processes 9 mm out through a slimmer back after the
# field has spent its whole squeeze (measured). A push moves a vertex only as
# far as it must to clear the skin by TUCK_MIN_CLEAR, so the cap binds on the
# extremes alone -- and every one of them is a bone TIP buried in soft tissue.
TUCK_PUSH_MAX = 0.010  # a local push may not move a vertex further
TUCK_PUSH_SKIRT = 0.6  # how much of a push its unpushed neighbours carry


AXIS_NAME = ('width', 'depth', 'height')


def _silhouette_columns(body, key_axes, val_axis, cell=0.02, step=0.01, min_span=0.03):
    """cell -> (low, high) of the skin along ``val_axis``, over its FACES.

    ``_skin_columns`` counts VERTICES, and the base body's torso is coarse: it
    keeps 498 columns out of the body, misses the pelvis and the lumbar spine
    completely, and under-reads the chest by 9 mm (measured against the same
    test run on the GLB, whose UV seams trebled the vertex count). A tuck is
    only as honest as the surface it is fitted against, so this one walks the
    POLYGONS and samples each one on a grid no coarser than half a cell. Every
    cell a face crosses gets samples, whatever the mesh's density.
    """
    mw = body.matrix_world
    me = body.data
    cols = {}

    def put(p):
        key = (int(math.floor(p[key_axes[0]] / cell)), int(math.floor(p[key_axes[1]] / cell)))
        v = p[val_axis]
        band = cols.get(key)
        if band is None:
            cols[key] = [v, v]
        else:
            if v < band[0]:
                band[0] = v
            if v > band[1]:
                band[1] = v

    for poly in me.polygons:
        pts = [mw @ me.vertices[i].co for i in poly.vertices]
        for k in range(1, len(pts) - 1):
            a, b, c = pts[0], pts[k], pts[k + 1]
            reach = max((b - a).length, (c - a).length, (c - b).length)
            n = max(1, int(math.ceil(reach / step)))
            for i in range(n + 1):
                for j in range(n + 1 - i):
                    put(a + (b - a) * (i / n) + (c - a) * (j / n))
    return {
        'cols': {k: (v[0], v[1]) for k, v in cols.items() if v[1] - v[0] >= min_span},
        'key_axes': key_axes,
        'val_axis': val_axis,
        'cell': cell,
    }


def _skin_depth_columns(body):
    """front/back of the skin per (x, z) cell -- what a chest bone must clear."""
    return _silhouette_columns(body, (0, 2), 1)


def _probes(obj, col):
    """[(height, coordinate, low, high)] for this piece against one silhouette."""
    ka, va, cell, cols = col['key_axes'], col['val_axis'], col['cell'], col['cols']
    mw = obj.matrix_world
    verts = obj.data.vertices
    out = []
    for i in range(0, len(verts), TUCK_STRIDE):
        co = mw @ verts[i].co
        band = cols.get((int(math.floor(co[ka[0]] / cell)), int(math.floor(co[ka[1]] / cell))))
        if band is not None:
            out.append((co.z, co[va], band[0], band[1]))
    return out


def _clearance(probes):
    """The tightest gap between these vertices and the skin. Negative = out."""
    worst = 1e9
    for _h, v, lo, hi in probes:
        gap = min(v - lo, hi - v)
        if gap < worst:
            worst = gap
    return worst


def _d_interval(probes, a, centre, margin=TUCK_MARGIN):
    """The slides that keep every probe inside the skin at this squeeze."""
    lo, hi = -1e9, 1e9
    for _h, v, low, high in probes:
        u = v - centre
        lo = max(lo, (low + margin - centre) - a * u)
        hi = min(hi, (high - margin - centre) - a * u)
    return lo, hi


def _tuck_band(probes, centre, floor=TUCK_SCALE_FLOOR):
    """-> (a, d, feasible): the least squeeze, the most margin it allows.

    THE MARGIN IS A WANT, CONTAINMENT IS THE NEED. Asking every band for the
    full TUCK_MARGIN and letting it squeeze to get there put a 10 % depth
    squeeze into a band whose skin is barely 2 x TUCK_MARGIN thick (measured:
    the shoulder cap), which is a centimetre of thorax moved to buy 2 mm of
    slack nobody needs. So `a` is walked down from 1 and, at each step, the
    LARGEST margin that band can actually hold is taken. A band that fits with
    no squeeze is never squeezed."""
    wants = [TUCK_MARGIN - (TUCK_MARGIN - TUCK_MIN_CLEAR) * k / 4.0 for k in range(5)]
    steps = TUCK_STEPS if floor < 1.0 else 1
    for step in range(steps):
        a = 1.0 - (1.0 - floor) * step / float(steps - 1) if steps > 1 else 1.0
        for margin in wants:
            lo, hi = _d_interval(probes, a, centre, margin)
            if lo <= hi:
                d = 0.0 if lo <= 0.0 <= hi else (lo if lo > 0.0 else hi)
                return a, d, True
    lo, hi = _d_interval(probes, floor, centre, TUCK_MIN_CLEAR)
    return floor, 0.5 * (lo + hi), False


def _tuck_field(objs, col, floor=TUCK_SCALE_FLOOR):
    """Fit v' = c + a(z)*(v-c) + d(z) on one silhouette. -> (field, c, report).

    The centre is the pieces' own middle on that axis, so the least-squeeze
    solution is the one that moves the two sides in by the same amount."""
    probes = []
    for obj in objs:
        probes.extend(_probes(obj, col))
    if not probes:
        return None, 0.0, None
    vs = [p[1] for p in probes]
    zs = [p[0] for p in probes]
    c = 0.5 * (min(vs) + max(vs))
    z0, z1 = min(zs), max(zs)
    n = max(1, int(math.ceil((z1 - z0) / TUCK_BAND)))
    width = (z1 - z0) / n if n else TUCK_BAND

    buckets = [[] for _ in range(n)]
    for p in probes:
        i = int((p[0] - z0) / width) if width > 0 else 0
        buckets[min(max(i, 0), n - 1)].append(p)

    solved = [_tuck_band(b, c, floor) if b else None for b in buckets]
    # a band with no vertex of its own inherits its neighbour, so the field
    # never snaps back to identity in a gap and then out again
    for i in range(n):
        if solved[i] is None:
            solved[i] = (
                next((solved[j] for j in range(i, -1, -1) if solved[j]), None)
                or next((solved[j] for j in range(i, n) if solved[j]), None)
                or (1.0, 0.0, True)
            )
    # no band may be less squeezed than its neighbours: a step in `a` is a kink
    a_s = [min(solved[max(i - 1, 0)][0], solved[i][0], solved[min(i + 1, n - 1)][0]) for i in range(n)]
    out = []
    ok = True
    for i in range(n):
        d, feasible = 0.0, False
        for margin in [TUCK_MARGIN - (TUCK_MARGIN - TUCK_MIN_CLEAR) * k / 4.0 for k in range(5)]:
            lo, hi = _d_interval(buckets[i], a_s[i], c, margin) if buckets[i] else (-1e9, 1e9)
            if lo <= hi:
                d, feasible = (0.0 if lo <= 0.0 <= hi else (lo if lo > 0.0 else hi)), True
                break
        if not feasible:
            lo, hi = _d_interval(buckets[i], a_s[i], c, TUCK_MIN_CLEAR)
            d, ok = 0.5 * (lo + hi), False
        out.append((z0 + (i + 0.5) * width, a_s[i], d))

    def field(z):
        if z <= out[0][0]:
            return out[0][1], out[0][2]
        if z >= out[-1][0]:
            return out[-1][1], out[-1][2]
        for k in range(len(out) - 1):
            zc0, a0, d0 = out[k]
            zc1, a1, d1 = out[k + 1]
            if z <= zc1:
                t = (z - zc0) / (zc1 - zc0)
                return a0 + t * (a1 - a0), d0 + t * (d1 - d0)
        return out[-1][1], out[-1][2]

    report = {
        'axis': AXIS_NAME[col['val_axis']],
        'centre_m': round(c, 4),
        'bands': [[round(zc, 3), round(a, 4), round(1000.0 * d, 2)] for zc, a, d in out],
        'scale_min': round(min(a_s), 4),
        'slide_mm_max': round(1000.0 * max(abs(d) for _zc, _a, d in out), 2),
        'band_feasible': ok,
    }
    return field, c, report


def _apply_field(objs, field, c, axis):
    for obj in objs:
        mw = obj.matrix_world.copy()
        inv = mw.inverted()
        for v in obj.data.vertices:
            co = mw @ v.co
            a, d = field(co.z)
            co[axis] = c + a * (co[axis] - c) + d
            v.co = inv @ co
        obj.data.update()
    bpy.context.view_layer.update()


def _tuck_push(skel, bvh, bones, clear=TUCK_MIN_CLEAR):
    """Push the stragglers of these groups back under the skin. -> report."""
    me = skel.data
    mw = skel.matrix_world.copy()
    inv = mw.inverted()
    names = [vg.name for vg in skel.vertex_groups]
    want = set(bones)
    disp = {}
    for v in me.vertices:
        if not v.groups or names[max(v.groups, key=lambda g: g.weight).group] not in want:
            continue
        co = mw @ v.co
        loc, nor, _idx, _d = bvh.find_nearest(co)
        if loc is None:
            continue
        need = (co - loc).dot(nor) + clear
        if need > 0.0:
            disp[v.index] = nor * -min(need, TUCK_PUSH_MAX)
    if not disp:
        return {'vertices': 0, 'worst_mm': 0.0, 'skirt': 0}
    # a skirt over the one-ring: a vertex pushed on its own is a dimple
    ring = {}
    for e in me.edges:
        a, b = e.vertices
        if a in disp and b not in disp:
            ring.setdefault(b, []).append(disp[a])
        elif b in disp and a not in disp:
            ring.setdefault(a, []).append(disp[b])
    worst = max(d.length for d in disp.values())
    for i, d in disp.items():
        me.vertices[i].co = inv @ ((mw @ me.vertices[i].co) + d)
    for i, ds in ring.items():
        acc = Vector((0.0, 0.0, 0.0))
        for d in ds:
            acc += d
        acc *= TUCK_PUSH_SKIRT / len(ds)
        me.vertices[i].co = inv @ ((mw @ me.vertices[i].co) + acc)
    me.update()
    bpy.context.view_layer.update()
    return {'vertices': len(disp), 'worst_mm': round(1000.0 * worst, 2), 'skirt': len(ring)}


def _tuck_trunk(pieces, mapping, col):
    """Pull the trunk back inside the skin. -> report per tuck unit.

    Run more than once: the field is linear between band centres, so the first
    pass leaves a fraction of a millimetre where two bands disagree, and a
    second pass on the moved geometry takes it out.

    ONLY THE FIRST PASS MAY SQUEEZE. Every pass re-solves from the geometry the
    last one left, so a squeeze in each of them MULTIPLIES: the female body,
    whose chest the male thorax misses by 24 mm, hit the floor three times over
    and came out 27 % shallower (measured). A refinement pass slides and nothing
    more, which bounds the whole reshape by TUCK_SCALE_FLOOR."""
    report = {}
    for unit, bones in TUCK_UNITS:
        objs = [pieces[s_] for s_ in sorted(mapping) if mapping[s_] in bones]
        if not objs:
            continue

        def clear(objs=objs):
            return _clearance([p for obj in objs for p in _probes(obj, col)])

        before = clear()
        if before >= TUCK_MIN_CLEAR:
            continue
        passes = []
        for _n in range(TUCK_PASSES):
            field, c, info = _tuck_field(objs, col, TUCK_SCALE_FLOOR if _n == 0 else 1.0)
            if field is None:
                break
            _apply_field(objs, field, c, col['val_axis'])
            got = clear()
            step = {'depth': info, 'clearance_mm': round(1000.0 * got, 2)}
            passes.append(step)
            if got >= TUCK_MIN_CLEAR:
                break
        report[unit] = {
            'pieces': len(objs),
            'passes': passes,
            'clearance_before_mm': round(1000.0 * before, 2),
            'clearance_after_mm': passes[-1]['clearance_mm'] if passes else None,
            'cleared': bool(passes) and passes[-1]['clearance_mm'] >= 1000.0 * TUCK_MIN_CLEAR,
        }
    return report


def _piece_box(obj):
    mw = obj.matrix_world
    lo = [1e9] * 3
    hi = [-1e9] * 3
    for v in obj.data.vertices:
        co = mw @ v.co
        for i in range(3):
            lo[i] = min(lo[i], co[i])
            hi[i] = max(hi[i], co[i])
    return lo, hi
